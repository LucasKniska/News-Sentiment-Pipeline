import logging
from datetime import date, timedelta

from finnhub_client import fetch_company_news, get_client

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Static snapshot of ~100 large-cap US tickers by market cap (roughly S&P 100
# membership). Not pulled from a live index feed - refresh manually as needed.
DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "BRK.B", "AVGO", "TSLA", "LLY",
    "JPM", "V", "UNH", "XOM", "MA", "PG", "COST", "HD", "JNJ", "NFLX",
    "MRK", "ABBV", "CVX", "BAC", "CRM", "KO", "AMD", "PEP", "WMT", "ADBE",
    "TMO", "MCD", "CSCO", "ACN", "LIN", "ABT", "WFC", "DHR", "GE", "QCOM",
    "IBM", "TXN", "CAT", "VZ", "AMGN", "PM", "INTU", "NOW", "ISRG", "SPGI",
    "CMCSA", "DIS", "AXP", "RTX", "UNP", "NEE", "GS", "T", "LOW", "HON",
    "BKNG", "AMAT", "PFE", "SYK", "COP", "BLK", "ELV", "TJX", "MS", "SCHW",
    "PLD", "VRTX", "ETN", "LMT", "C", "GILD", "MDT", "DE", "ADI", "CI",
    "BSX", "REGN", "ADP", "SBUX", "BA", "MMC", "SO", "PANW", "UPS", "ZTS",
    "CB", "BX", "MU", "KLAC", "SLB", "DUK", "SNPS", "CDNS", "MO", "EQIX",
]


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
