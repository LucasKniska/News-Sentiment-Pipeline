import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Callable

from chain import extract_with_fallback, relevant_tickers
from combine_chain import combine_signal
from db import (
    fetch_latest_signal,
    fetch_new_articles,
    fetch_uncombined_sentiment,
    get_connection,
    insert_signal,
    mark_attempted,
    upsert_article_sentiment,
)
from models import Article
from schema import TRACKED_TICKERS, ArticleExtraction

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Bounded rather than one thread per candidate article - a busy day can have 100+
# candidates, and firing them all at once would just blow through Groq's per-model
# rate limit and push everything down the fallback ladder together instead of
# individual articles falling back independently.
MAX_EXTRACTION_WORKERS = 8


def run(target_date: date | None = None) -> dict:
    # Defaults to yesterday, not today: lambda/news_ingestion/handler.py fetches
    # from_date = to_date - 1 day, and this runs at 4am ET, 3 hours after
    # ingestion's 1am ET run (see terraform/schedule.tf), so by the time this
    # runs, yesterday's articles are the complete/stable set while today's may
    # not exist yet.
    target_date = target_date or (date.today() - timedelta(days=1))

    conn = get_connection()
    try:
        previous_by_ticker = {
            ticker: fetch_latest_signal(conn, ticker, target_date)
            for ticker in TRACKED_TICKERS
        }

        # Union of articles new for at least one tracked ticker - each gets exactly
        # one LLM call this run regardless of how many tracked tickers it mentions.
        # "New" means no article_extraction_attempts row yet for that (article,
        # ticker) pair - see db.py's _SELECT_NEW_ARTICLES_SQL.
        candidate_articles: dict[int, Article] = {}
        for ticker in TRACKED_TICKERS:
            for article in fetch_new_articles(conn, ticker, target_date):
                candidate_articles[article.id] = article

        # Extraction calls are independent per article (pure network calls to
        # Groq/Anthropic, no shared state) so they run concurrently; the DB
        # connection isn't thread-safe, so every write below happens back on the
        # main thread once all extractions have completed.
        extraction_results: dict[int, ArticleExtraction] = {}
        with ThreadPoolExecutor(max_workers=MAX_EXTRACTION_WORKERS) as pool:
            future_to_article = {
                pool.submit(extract_with_fallback, article): article
                for article in candidate_articles.values()
            }
            for future in as_completed(future_to_article):
                article = future_to_article[future]
                try:
                    result, model_used = future.result()
                except Exception:
                    logger.warning(
                        "Extraction failed for article %s on every fallback model",
                        article.id,
                        exc_info=True,
                    )
                    continue
                if model_used:
                    logger.info("Article %s extracted via %s", article.id, model_used)
                extraction_results[article.id] = result

        for article_id, result in extraction_results.items():
            # Marks every ticker the chain was actually asked about as attempted -
            # including ones the model correctly left out (paywalled/blocked text,
            # or an omitted ticker) - so fetch_new_articles never re-offers this
            # pair. Only for articles that got a response at all: one that failed
            # on every fallback model isn't in extraction_results, so it stays
            # unattempted and eligible for retry next run.
            tickers_asked = relevant_tickers(candidate_articles[article_id])
            if tickers_asked:
                mark_attempted(conn, article_id, tickers_asked)
            if result.ticker_sentiments:
                upsert_article_sentiment(conn, article_id, result.ticker_sentiments)

        # Reads combine input back from article_sentiment rather than from this
        # run's in-memory extraction_results - self-healing, since it also picks
        # up anything extracted-but-never-combined from an earlier run (e.g. a
        # prior combine_signal failure) rather than only what was just extracted.
        signal_counts = {}
        for ticker in TRACKED_TICKERS:
            previous = previous_by_ticker[ticker]
            already_ids = previous["article_ids"] if previous else []
            new_entries = fetch_uncombined_sentiment(
                conn, ticker, target_date, already_ids
            )
            if not new_entries:
                continue
            try:
                combined = combine_signal(previous, new_entries, ticker)
            except Exception:
                logger.warning("Combine failed for ticker %s", ticker, exc_info=True)
                continue
            insert_signal(
                conn,
                ticker=ticker,
                event_type=combined["event_type"],
                sentiment=combined["sentiment"],
                involvement=combined["involvement"],
                article_ids=combined["article_ids"],
            )
            signal_counts[ticker] = len(new_entries)
        conn.commit()
    finally:
        conn.close()

    return {
        "signal_counts": signal_counts,
        "candidates": len(candidate_articles),
        "extracted": len(extraction_results),
    }


def _has_remaining_work(conn, target_date: date) -> bool:
    # Two distinct kinds of remaining work, checked separately: articles never
    # attempted at all, and articles already extracted but not yet folded into a
    # signal (e.g. a prior combine_signal failure). Only checking the former was
    # the original bug - a date could sit forever in the second state, since
    # nothing here would ever notice.
    for ticker in TRACKED_TICKERS:
        if fetch_new_articles(conn, ticker, target_date):
            return True
        previous = fetch_latest_signal(conn, ticker, target_date)
        already_ids = previous["article_ids"] if previous else []
        if fetch_uncombined_sentiment(conn, ticker, target_date, already_ids):
            return True
    return False


# Runs the same attempt-and-retry loop run_backfill uses for one date: up to
# max_attempts calls to run(), stopping early on a quota-exhaustion signal or a
# low-time signal. Returns a terminal status string to propagate immediately
# ("stopped_quota_exhausted"/"stopped_low_on_time"), or None once the date has
# no remaining work (resolved) or has been retried max_attempts times without
# resolving (moving on - see the module-level note above _has_remaining_work
# on why a date can legitimately never fully resolve).
def _fill_date(
    conn,
    target_date: date,
    max_attempts: int,
    get_remaining_ms: Callable[[], int] | None,
    safety_margin_ms: int,
    results: dict[str, dict],
) -> str | None:
    if not _has_remaining_work(conn, target_date):
        return None

    attempts = 0
    while True:
        if get_remaining_ms is not None and get_remaining_ms() < safety_margin_ms:
            return "stopped_low_on_time"

        attempts += 1
        stats = run(target_date)
        results[target_date.isoformat()] = stats

        if stats["extracted"] < stats["candidates"]:
            return "stopped_quota_exhausted"

        if not _has_remaining_work(conn, target_date):
            return None
        if attempts >= max_attempts:
            logger.warning(
                "Date %s still has remaining work after %d attempts (likely a persistent combine/insert "
                "failure) - moving on rather than retrying indefinitely",
                target_date,
                attempts,
            )
            return None


# Groq's account-wide daily token quota (TPD) is the actual bottleneck for
# backfilling old dates - see RESUME_SENTIMENT_BACKFILL.md. This lets a fixed
# EventBridge schedule (static backfill_range input, see handler.py) make a
# bit more progress every morning without any human watching console output
# for 429s: each invocation works forward through the range, skipping dates
# that already have no remaining work (cheap DB reads only, no LLM calls),
# and stops itself once a date shows a partial extraction failure - the best
# available signal (short of parsing Groq's error text, which is brittle)
# that the day's quota is probably exhausted, so grinding through the rest of
# the range would just be doomed API calls. The next morning's invocation
# naturally retries whatever's still incomplete, via the same DB-derived
# "what's new" check run() already uses for same-day resumability.
#
# Before touching the historical range at all, this first runs the same
# attempt loop against the most recent day - the same target_date the live
# 4am ET schedule processes (see run()'s own default). That daily run has no
# retry of its own: if Groq's quota was already tight by 4am, yesterday can be
# left partially processed with nothing to catch it up except this 5am
# invocation. A fresh signal matters more than an old backfill date, so this
# tops up yesterday first and only spends whatever time/quota is left on the
# historical range - on a morning where yesterday alone exhausts the quota,
# the range gets zero progress that day, which is the correct tradeoff.
def run_backfill(
    start_date: date, end_date: date, get_remaining_ms: Callable[[], int] | None = None
) -> dict:
    # Reserves enough runway for one more date's worst-case duration (matches
    # the live daily schedule's own 900s/15min Lambda timeout) rather than
    # letting Lambda kill an invocation mid-call.
    SAFETY_MARGIN_MS = 600_000
    MAX_ATTEMPTS_PER_DATE = 2

    conn = get_connection()
    try:
        results: dict[str, dict] = {}

        most_recent_date = date.today() - timedelta(days=1)
        status = _fill_date(
            conn,
            most_recent_date,
            MAX_ATTEMPTS_PER_DATE,
            get_remaining_ms,
            SAFETY_MARGIN_MS,
            results,
        )
        if status is not None:
            return {"status": status, "results": results}

        cursor_date = start_date
        while cursor_date <= end_date:
            if get_remaining_ms is not None and get_remaining_ms() < SAFETY_MARGIN_MS:
                return {"status": "stopped_low_on_time", "results": results}

            # Already handled above if the range happens to include today's target.
            if cursor_date == most_recent_date:
                cursor_date += timedelta(days=1)
                continue

            status = _fill_date(
                conn,
                cursor_date,
                MAX_ATTEMPTS_PER_DATE,
                get_remaining_ms,
                SAFETY_MARGIN_MS,
                results,
            )
            if status is not None:
                return {"status": status, "results": results}

            cursor_date += timedelta(days=1)

        return {"status": "complete", "results": results}
    finally:
        conn.close()
