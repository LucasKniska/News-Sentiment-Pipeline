import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Callable

from chain import extract_with_fallback
from combine_chain import build_combine_chain, combine_signal
from db import fetch_latest_signal, fetch_new_articles, get_connection, insert_signal, upsert_article_sentiment
from models import Article
from schema import TRACKED_TICKERS, ArticleExtraction, TickerSentiment

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
        previous_by_ticker = {ticker: fetch_latest_signal(conn, ticker, target_date) for ticker in TRACKED_TICKERS}
        already_ids_by_ticker = {
            ticker: (previous_by_ticker[ticker]["article_ids"] if previous_by_ticker[ticker] else [])
            for ticker in TRACKED_TICKERS
        }

        # Union of articles new for at least one tracked ticker - each gets exactly
        # one LLM call this run regardless of how many tracked tickers it mentions.
        candidate_articles: dict[int, Article] = {}
        for ticker in TRACKED_TICKERS:
            for article in fetch_new_articles(conn, ticker, already_ids_by_ticker[ticker], target_date):
                candidate_articles[article.id] = article

        combine_chain = build_combine_chain()
        new_entries_by_ticker: dict[str, list[tuple[int, TickerSentiment]]] = {ticker: [] for ticker in TRACKED_TICKERS}

        # Extraction calls are independent per article (pure network calls to
        # Groq/Anthropic, no shared state) so they run concurrently; the DB
        # connection isn't thread-safe, so every write below happens back on the
        # main thread once all extractions have completed.
        extraction_results: dict[int, ArticleExtraction] = {}
        with ThreadPoolExecutor(max_workers=MAX_EXTRACTION_WORKERS) as pool:
            future_to_article = {pool.submit(extract_with_fallback, article): article for article in candidate_articles.values()}
            for future in as_completed(future_to_article):
                article = future_to_article[future]
                try:
                    result, model_used = future.result()
                except Exception:
                    logger.warning("Extraction failed for article %s on every fallback model", article.id, exc_info=True)
                    continue
                if model_used:
                    logger.info("Article %s extracted via %s", article.id, model_used)
                extraction_results[article.id] = result

        for article_id, result in extraction_results.items():
            if result.ticker_sentiments:
                upsert_article_sentiment(conn, article_id, result.ticker_sentiments)
            for ts in result.ticker_sentiments:
                # A ticker on this article may already be counted (e.g. it was new
                # for a different tracked ticker mentioned in the same article, but
                # this one was processed in an earlier run) - skip re-counting it.
                if article_id not in already_ids_by_ticker[ts.ticker]:
                    new_entries_by_ticker[ts.ticker].append((article_id, ts))

        signal_counts = {}
        for ticker, new_entries in new_entries_by_ticker.items():
            if not new_entries:
                continue
            try:
                combined = combine_signal(previous_by_ticker[ticker], new_entries, ticker, combine_chain)
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
    for ticker in TRACKED_TICKERS:
        previous = fetch_latest_signal(conn, ticker, target_date)
        already_ids = previous["article_ids"] if previous else []
        if fetch_new_articles(conn, ticker, already_ids, target_date):
            return True
    return False


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
def run_backfill(start_date: date, end_date: date, get_remaining_ms: Callable[[], int] | None = None) -> dict:
    # Reserves enough runway for one more date's worst-case duration (matches
    # the live daily schedule's own 900s/15min Lambda timeout) rather than
    # letting Lambda kill an invocation mid-call.
    SAFETY_MARGIN_MS = 600_000
    MAX_ATTEMPTS_PER_DATE = 2

    conn = get_connection()
    try:
        cursor_date = start_date
        results: dict[str, dict] = {}
        while cursor_date <= end_date:
            if get_remaining_ms is not None and get_remaining_ms() < SAFETY_MARGIN_MS:
                return {"status": "stopped_low_on_time", "results": results}

            if not _has_remaining_work(conn, cursor_date):
                cursor_date += timedelta(days=1)
                continue

            target_date = cursor_date
            attempts = 0
            while True:
                attempts += 1
                stats = run(target_date)
                results[target_date.isoformat()] = stats

                if stats["extracted"] < stats["candidates"]:
                    return {"status": "stopped_quota_exhausted", "results": results}

                if not _has_remaining_work(conn, target_date):
                    break
                if attempts >= MAX_ATTEMPTS_PER_DATE:
                    logger.warning(
                        "Date %s still has remaining work after %d attempts (likely a persistent combine/insert "
                        "failure) - moving on rather than retrying indefinitely",
                        target_date, attempts,
                    )
                    break

            cursor_date = target_date + timedelta(days=1)

        return {"status": "complete", "results": results}
    finally:
        conn.close()
