import logging
import os
from datetime import date, timedelta

from db import get_connection, upsert_articles, upsert_daily_price
from finnhub_client import fetch_company_news, fetch_quote, get_client
from scraper import fetch_article_text
from transform import to_article_row, to_price_row

logger = logging.getLogger()
logger.setLevel(logging.INFO)


DEFAULT_TICKERS = os.environ.get("TICKERS", "NVDA,LMT,XOM,AUR,AAPL").split(",")

# Caps worst-case runtime/cost per ticker per day - a busy ticker/day can return
# 100+ articles (the AAPL smoke test alone pulled 176), and each one costs a
# sequential scrape here plus, later, an LLM extraction call downstream.
MAX_ARTICLES_PER_TICKER_PER_DAY = 50

# Caps total articles stored across all tickers in one invocation - the per-ticker
# cap alone doesn't bound this (e.g. backfill_run.py calling lambda_handler once
# per historical day, or TICKERS growing past 5 tickers).
MAX_ARTICLES_PER_DAY_TOTAL = 250


def lambda_handler(event, context):
    event = event or {}
    tickers = event.get("tickers", DEFAULT_TICKERS)

    # Optional historical range override for backfills (see backfill_run.py).
    # Absent in the daily scheduled invocation, so that path is unchanged:
    # today's quote is still fetched/written, which wouldn't make sense for a
    # past from_date/to_date (Finnhub's /quote has no historical mode).
    is_backfill = "from_date" in event or "to_date" in event
    if is_backfill:
        to_date = date.fromisoformat(event["to_date"]) if event.get("to_date") else date.today()
        from_date = date.fromisoformat(event["from_date"]) if event.get("from_date") else to_date
    else:
        to_date = date.today()
        from_date = to_date - timedelta(days=1)

    client = get_client()
    conn = get_connection()

    articles_by_ticker = {}
    total_articles_today = 0
    try:
        for ticker in tickers:
            try:
                raw_articles = fetch_company_news(client, ticker, from_date, to_date)
            except Exception:
                logger.warning("Failed to fetch news for %s", ticker, exc_info=True)
                continue

            logger.info("Fetched %d articles for %s (%s to %s)", len(raw_articles), ticker, from_date, to_date)
            if len(raw_articles) > MAX_ARTICLES_PER_TICKER_PER_DAY:
                logger.info("Capping %s to %d articles", ticker, MAX_ARTICLES_PER_TICKER_PER_DAY)
                raw_articles = raw_articles[:MAX_ARTICLES_PER_TICKER_PER_DAY]

            remaining_budget = max(MAX_ARTICLES_PER_DAY_TOTAL - total_articles_today, 0)
            if len(raw_articles) > remaining_budget:
                logger.info("Capping %s to %d articles (daily budget of %d reached)", ticker, remaining_budget, MAX_ARTICLES_PER_DAY_TOTAL)
                raw_articles = raw_articles[:remaining_budget]

            price_row = None
            if not is_backfill:
                try:
                    price_row = to_price_row(ticker, fetch_quote(client, ticker))
                except Exception:
                    logger.warning("Failed to fetch price for %s", ticker, exc_info=True)
                    price_row = None

            rows = [to_article_row(article, fetch_article_text(article["url"])) for article in raw_articles]
            with conn.transaction():
                upsert_articles(conn, rows)
                upsert_daily_price(conn, price_row)
            articles_by_ticker[ticker] = rows
            total_articles_today += len(rows)
    finally:
        conn.close()

    return {
        "statusCode": 200,
        "articleCounts": {ticker: len(articles) for ticker, articles in articles_by_ticker.items()},
    }
