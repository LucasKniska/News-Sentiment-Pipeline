import logging
from datetime import date, timedelta

from chain import build_chain, extract
from combine_chain import build_combine_chain, combine_signal
from db import fetch_latest_signal, fetch_new_articles, get_connection, insert_signal
from models import Article
from schema import TRACKED_TICKERS, TickerSentiment

logger = logging.getLogger()
logger.setLevel(logging.INFO)


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

        chain = build_chain()
        combine_chain = build_combine_chain()
        new_entries_by_ticker: dict[str, list[tuple[int, TickerSentiment]]] = {ticker: [] for ticker in TRACKED_TICKERS}
        for article in candidate_articles.values():
            try:
                result = extract(article, chain)
            except Exception:
                logger.warning("Extraction failed for article %s", article.id, exc_info=True)
                continue
            for ts in result.ticker_sentiments:
                # A ticker on this article may already be counted (e.g. it was new
                # for a different tracked ticker mentioned in the same article, but
                # this one was processed in an earlier run) - skip re-counting it.
                if article.id not in already_ids_by_ticker[ts.ticker]:
                    new_entries_by_ticker[ts.ticker].append((article.id, ts))

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
