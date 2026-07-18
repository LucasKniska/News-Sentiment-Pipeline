import os

import boto3
import psycopg

# The same article id can come back under multiple tickers (each fetched
# separately), but `related` only ever echoes the ticker that was queried -
# merging on conflict is the only way the tickers array reflects every
# ticker that actually mentions the article.
_UPSERT_SQL = """
    INSERT INTO articles (id, headline, text, url, datetime, tickers)
    VALUES (%(id)s, %(headline)s, %(text)s, %(url)s, %(datetime)s, %(tickers)s)
    ON CONFLICT (id) DO UPDATE SET
        tickers = COALESCE(
            (SELECT array_agg(DISTINCT t) FROM unnest(articles.tickers || EXCLUDED.tickers) AS t),
            '{}'
        )
"""


def get_connection() -> psycopg.Connection:
    # The deployed Lambda authenticates with a short-lived IAM token instead of
    # PGPASSWORD (its security group allows 0.0.0.0/0, so a static password
    # alone isn't enough protection) - local dev keeps using PGPASSWORD from
    # .env via psycopg's normal libpq env var handling.
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


def upsert_articles(conn: psycopg.Connection, rows: list[dict]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, rows)
