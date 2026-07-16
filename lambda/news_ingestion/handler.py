import logging
from datetime import date, timedelta

from finnhub_client import fetch_company_news, get_client

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_TICKERS = ["AAPL"]


def lambda_handler(event, context):
    event = event or {}
    tickers = event.get("tickers", DEFAULT_TICKERS)

    to_date = date.today()
    from_date = to_date - timedelta(days=1)

    client = get_client()

    articles_by_ticker = {}
    for ticker in tickers:
        articles = fetch_company_news(client, ticker, from_date, to_date)
        logger.info("Fetched %d articles for %s (%s to %s)", len(articles), ticker, from_date, to_date)
        articles_by_ticker[ticker] = articles

    return {
        "statusCode": 200,
        "articleCounts": {ticker: len(articles) for ticker, articles in articles_by_ticker.items()},
        "articles": articles_by_ticker,
    }
