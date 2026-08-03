import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

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
    # from_date = to_date - 1 day, and there's no scheduled trigger yet, so by the
    # time this runs, yesterday's articles are the complete/stable set while
    # today's may not exist yet.
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

    return signal_counts
