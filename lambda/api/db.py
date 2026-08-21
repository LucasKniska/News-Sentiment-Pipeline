import os

import boto3
import psycopg

# headlines is a correlated subquery over articles rather than a JOIN, since
# s.article_ids is an array (informal FK, see CLAUDE.md) - a JOIN would need an
# unnest + re-aggregate per signal row anyway, so the subquery is simpler here.
_SELECT_RECENT_SIGNALS_SQL = """
    SELECT s.id, s.ticker, s.timestamp, s.event_type, s.sentiment, s.involvement, s.article_ids,
           (SELECT array_agg(a.headline ORDER BY a.datetime DESC)
            FROM articles a WHERE a.id = ANY(s.article_ids)) AS headlines
    FROM signals s
    WHERE %(ticker)s::text IS NULL OR s.ticker = %(ticker)s
    ORDER BY s.timestamp DESC
    LIMIT %(limit)s
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


def fetch_recent_signals(
    conn: psycopg.Connection, limit: int, ticker: str | None = None
) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(_SELECT_RECENT_SIGNALS_SQL, {"limit": limit, "ticker": ticker})
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "ticker": row[1],
            "timestamp": row[2].isoformat(),
            "event_type": row[3],
            "sentiment": float(row[4]),
            "involvement": float(row[5]),
            "article_ids": list(row[6]),
            "headlines": list(row[7]) if row[7] else [],
        }
        for row in rows
    ]
