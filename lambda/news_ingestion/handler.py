import logging
import os
from datetime import date, timedelta

from db import get_connection, upsert_articles
from finnhub_client import fetch_company_news, get_client
from scraper import fetch_article_text
from transform import to_article_row

logger = logging.getLogger()
logger.setLevel(logging.INFO)


DEFAULT_TICKERS = os.environ.get("TICKERS", "NVDA,LMT,XOM,AUR,AAPL").split(",")


def lambda_handler(event, context):
    event = event or {}
    tickers = event.get("tickers", DEFAULT_TICKERS)

    to_date = date.today()
    from_date = to_date - timedelta(days=1)

    client = get_client()
    conn = get_connection()

    articles_by_ticker = {}
    try:
        for ticker in tickers:
            try:
                raw_articles = fetch_company_news(client, ticker, from_date, to_date)
            except Exception:
                logger.warning("Failed to fetch news for %s", ticker, exc_info=True)
                continue

            logger.info("Fetched %d articles for %s (%s to %s)", len(raw_articles), ticker, from_date, to_date)
            rows = [to_article_row(article, fetch_article_text(article["url"])) for article in raw_articles]
            with conn.transaction():
                upsert_articles(conn, rows)
            articles_by_ticker[ticker] = rows
    finally:
        conn.close()

    return {
        "statusCode": 200,
        "articleCounts": {ticker: len(articles) for ticker, articles in articles_by_ticker.items()},
    }
