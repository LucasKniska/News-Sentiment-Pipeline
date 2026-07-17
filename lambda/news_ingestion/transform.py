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
