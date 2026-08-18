import os
from datetime import date

import boto3
import psycopg

from models import Article
from schema import EventType, TickerSentiment

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
#
# Excludes on article_extraction_attempts, not on an explicit exclude_ids list -
# an attempt row exists once the chain has responded for this (article, ticker)
# pair regardless of what it said, including "no entry for this ticker" (see
# mark_attempted below). Using signals.article_ids for this instead (the
# original approach) meant an empty-result extraction left no record anywhere,
# so the same already-settled article kept coming back as "new" forever - see
# CLAUDE.md's 2026-08-17 note.
_SELECT_NEW_ARTICLES_SQL = """
    SELECT a.id, a.headline, a.text, a.url, a.datetime, a.tickers, a.ingested_at
    FROM articles a
    WHERE %(ticker)s = ANY(a.tickers)
      AND a.datetime::date = %(target_date)s
      AND a.text IS NOT NULL
      AND length(a.text) >= 100
      AND NOT EXISTS (
        SELECT 1 FROM article_extraction_attempts x
        WHERE x.article_id = a.id AND x.ticker = %(ticker)s
      )
"""

# Per-article extractions for this ticker/day that haven't been folded into a
# signal yet (not present in the latest signal's article_ids). Reads from
# article_sentiment rather than from the current run's in-memory extraction
# results, so a combine failure on an earlier run - or an earlier day's run -
# self-heals: the article shows up here again next time regardless of when it
# was extracted, instead of being silently dropped because it wasn't
# re-extracted this run.
_SELECT_UNCOMBINED_SENTIMENT_SQL = """
    SELECT s.article_id, s.sentiment, s.event_type, s.involvement
    FROM article_sentiment s
    JOIN articles a ON a.id = s.article_id
    WHERE s.ticker = %(ticker)s
      AND a.datetime::date = %(target_date)s
      AND NOT (s.article_id = ANY(%(exclude_ids)s))
"""

_INSERT_ATTEMPT_SQL = """
    INSERT INTO article_extraction_attempts (article_id, ticker)
    VALUES (%(article_id)s, %(ticker)s)
    ON CONFLICT (article_id, ticker) DO NOTHING
"""

_INSERT_SIGNAL_SQL = """
    INSERT INTO signals (ticker, event_type, sentiment, involvement, article_ids)
    VALUES (%(ticker)s, %(event_type)s, %(sentiment)s, %(involvement)s, %(article_ids)s)
"""

# ON CONFLICT DO UPDATE (not DO NOTHING) so a re-extraction of the same
# article/ticker pair - e.g. a rerun - overwrites rather than leaving a stale value.
_UPSERT_ARTICLE_SENTIMENT_SQL = """
    INSERT INTO article_sentiment (article_id, ticker, sentiment, involvement, event_type)
    VALUES (%(article_id)s, %(ticker)s, %(sentiment)s, %(involvement)s, %(event_type)s)
    ON CONFLICT (article_id, ticker) DO UPDATE SET
        sentiment = EXCLUDED.sentiment,
        involvement = EXCLUDED.involvement,
        event_type = EXCLUDED.event_type
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


def fetch_new_articles(conn: psycopg.Connection, ticker: str, target_date: date) -> list[Article]:
    with conn.cursor() as cur:
        cur.execute(_SELECT_NEW_ARTICLES_SQL, {"ticker": ticker, "target_date": target_date})
        columns = [desc[0] for desc in cur.description]
        return [Article(**dict(zip(columns, row))) for row in cur.fetchall()]


def mark_attempted(conn: psycopg.Connection, article_id: int, tickers: list[str]) -> None:
    """Records that the chain responded for (article_id, ticker), for every ticker
    it was asked about - regardless of whether that ticker ended up with a real
    entry in the response. See _SELECT_NEW_ARTICLES_SQL for why this exists."""
    with conn.cursor() as cur:
        for ticker in tickers:
            cur.execute(_INSERT_ATTEMPT_SQL, {"article_id": article_id, "ticker": ticker})


def fetch_uncombined_sentiment(conn: psycopg.Connection, ticker: str, target_date: date, exclude_ids: list[int]) -> list[tuple[int, TickerSentiment]]:
    """article_sentiment rows for this ticker/day not yet reflected in the latest
    signal's article_ids (pass that signal's article_ids as exclude_ids). reasoning
    isn't persisted (schema.py marks it TODO(cut-before-ship)), so reconstructed
    entries carry a placeholder - combine_chain.py only uses it as LLM-prompt
    context, not for anything stored.

    event_type also falls back to a placeholder for rows written before the
    2026-08-17 migration added that column (event_type IS NULL) - there turned
    out to be a large backlog of these: extracted successfully but never
    combined, from before combine_chain.py had its own model fallback
    (2026-08-16, see CLAUDE.md), so a quota-exhausted combine call silently
    dropped them. EventType(None) would raise; market_wide_movement is the
    designated catch-all category, and this only affects one input line in
    combine_chain.py's prompt context, not anything persisted."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_UNCOMBINED_SENTIMENT_SQL, {"ticker": ticker, "target_date": target_date, "exclude_ids": exclude_ids or []})
        rows = cur.fetchall()
    return [
        (
            article_id,
            TickerSentiment(
                ticker=ticker,
                sentiment=float(sentiment),
                event_type=EventType(event_type) if event_type else EventType.market_wide_movement,
                involvement=float(involvement),
                reasoning="(reconstructed from article_sentiment - original reasoning not persisted)",
            ),
        )
        for article_id, sentiment, event_type, involvement in rows
    ]


def insert_signal(conn: psycopg.Connection, ticker: str, event_type: str, sentiment: float, involvement: float, article_ids: list[int]) -> None:
    with conn.cursor() as cur:
        cur.execute(_INSERT_SIGNAL_SQL, {
            "ticker": ticker,
            "event_type": event_type,
            "sentiment": sentiment,
            "involvement": involvement,
            "article_ids": article_ids,
        })


def upsert_article_sentiment(conn: psycopg.Connection, article_id: int, ticker_sentiments: list[TickerSentiment]) -> None:
    """Records the raw per-ticker extraction output for one article - every entry
    the chain produced, regardless of whether it ended up "new" for that ticker's
    signals combine this run (see run.py)."""
    with conn.cursor() as cur:
        for ts in ticker_sentiments:
            cur.execute(_UPSERT_ARTICLE_SENTIMENT_SQL, {
                "article_id": article_id,
                "ticker": ts.ticker,
                "sentiment": ts.sentiment,
                "involvement": ts.involvement,
                "event_type": ts.event_type.value,
            })
