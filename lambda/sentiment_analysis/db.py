import os
from datetime import date

import boto3
import psycopg

from models import Article

# signals.timestamp is when the run executed, not the articles' publish date (see
# CLAUDE.md) - a run can process a target_date other than today (ingestion itself
# lags a day), so "the latest row for this ticker/day" has to be found by checking
# whether the row's article_ids actually contains an article published that day,
# not by trusting timestamp::date.
_SELECT_LATEST_SIGNAL_SQL = """
    SELECT s.sentiment, s.involvement, s.article_ids
    FROM signals s
    WHERE s.ticker = %(ticker)s
      AND EXISTS (
        SELECT 1 FROM articles a WHERE a.id = ANY(s.article_ids) AND a.datetime::date = %(target_date)s
      )
    ORDER BY s.timestamp DESC
    LIMIT 1
"""

# text IS NOT NULL excludes articles where both scraping and the Finnhub summary
# fallback failed (transform.py) - nothing for the chain to extract from. The length
# filter is a cheap prefilter for the most obviously-empty scrapes (e.g. a JS-blocked
# page whose only text is "Please enable JavaScript..."); it won't catch everything
# junky (a ~300-char paywall stub still passes) - the chain's own prompt handles those.
_SELECT_NEW_ARTICLES_SQL = """
    SELECT id, headline, text, url, datetime, tickers, ingested_at
    FROM articles
    WHERE %(ticker)s = ANY(tickers)
      AND datetime::date = %(target_date)s
      AND text IS NOT NULL
      AND length(text) >= 100
      AND NOT (id = ANY(%(exclude_ids)s))
"""

_INSERT_SIGNAL_SQL = """
    INSERT INTO signals (ticker, event_type, sentiment, involvement, article_ids)
    VALUES (%(ticker)s, %(event_type)s, %(sentiment)s, %(involvement)s, %(article_ids)s)
"""


def get_connection() -> psycopg.Connection:
    # Same IAM-auth branch as lambda/news_ingestion/db.py - duplicated rather than
    # imported, since each lambda/* directory zips independently as its own
    # deployment package (flat layout, no cross-directory imports).
    if os.environ.get("PG_IAM_AUTH", "").lower() == "true":
        host = os.environ["PGHOST"]
        port = int(os.environ.get("PGPORT", 5432))
        user = os.environ["PGUSER"]
        region = os.environ["AWS_REGION"]
        token = boto3.client("rds", region_name=region).generate_db_auth_token(
            DBHostname=host, Port=port, DBUsername=user, Region=region
        )
        return psycopg.connect(
            host=host,
            port=port,
            dbname=os.environ["PGDATABASE"],
            user=user,
            password=token,
            sslmode="require",
        )
    return psycopg.connect()


def fetch_latest_signal(conn: psycopg.Connection, ticker: str, target_date: date) -> dict | None:
    """Most recent signals row for this ticker whose article_ids covers
    target_date, or None if no run has processed that day for this ticker yet.
    Its article_ids is the full cumulative list for that day so far - doubles as
    the "already processed" set for this ticker/day."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_LATEST_SIGNAL_SQL, {"ticker": ticker, "target_date": target_date})
        row = cur.fetchone()
        if row is None:
            return None
        sentiment, involvement, article_ids = row
        return {"sentiment": float(sentiment), "involvement": float(involvement), "article_ids": list(article_ids)}


def fetch_new_articles(conn: psycopg.Connection, ticker: str, exclude_ids: list[int], target_date: date) -> list[Article]:
    with conn.cursor() as cur:
        cur.execute(_SELECT_NEW_ARTICLES_SQL, {"ticker": ticker, "exclude_ids": exclude_ids or [], "target_date": target_date})
        columns = [desc[0] for desc in cur.description]
        return [Article(**dict(zip(columns, row))) for row in cur.fetchall()]


def insert_signal(conn: psycopg.Connection, ticker: str, event_type: str, sentiment: float, involvement: float, article_ids: list[int]) -> None:
    with conn.cursor() as cur:
        cur.execute(_INSERT_SIGNAL_SQL, {
            "ticker": ticker,
            "event_type": event_type,
            "sentiment": sentiment,
            "involvement": involvement,
            "article_ids": article_ids,
        })
