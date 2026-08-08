import os

import boto3
import psycopg

# Reruns for the same ticker/date should overwrite, not duplicate - there's
# nothing to merge, the new close is just the correct value (same rationale
# as lambda/news_ingestion/db.py's _UPSERT_PRICE_SQL).
_UPSERT_PRICE_SQL = """
    INSERT INTO daily_prices (ticker, date, close)
    VALUES (%(ticker)s, %(date)s, %(close)s)
    ON CONFLICT (ticker, date) DO UPDATE SET close = EXCLUDED.close
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


def upsert_daily_prices(conn: psycopg.Connection, rows: list[dict]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_PRICE_SQL, rows)
