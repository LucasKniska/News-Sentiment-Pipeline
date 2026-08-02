from datetime import datetime

from pydantic import BaseModel


class Article(BaseModel):
    """Row shape of the `articles` table (db/schema.sql) - the sentiment
    extraction chain's input, as opposed to schema.py's ArticleExtraction,
    which is the chain's structured output."""

    id: int
    headline: str
    text: str | None
    url: str | None
    datetime: datetime
    tickers: list[str]
    ingested_at: datetime
