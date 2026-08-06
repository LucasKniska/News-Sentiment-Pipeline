from datetime import datetime, timezone


def _parse_tickers(related: str) -> list[str]:
    return [ticker.strip() for ticker in related.split(",") if ticker.strip()]


def to_article_row(article: dict, text: str | None) -> dict:
    return {
        "id": article["id"],
        "headline": article["headline"],
        "text": text or (article.get("summary") or None),
        "url": article["url"],
        "datetime": datetime.fromtimestamp(article["datetime"], tz=timezone.utc),
        "tickers": _parse_tickers(article.get("related", "")),
    }


def to_price_row(ticker: str, quote: dict) -> dict | None:
    # t=0 is Finnhub's "no data for this symbol" response (e.g. bad ticker) -
    # skip rather than write a garbage 1970-01-01 row.
    if not quote.get("t"):
        return None
    return {
        "ticker": ticker,
        "date": datetime.fromtimestamp(quote["t"], tz=timezone.utc).date(),
        "close": quote["c"],
    }
