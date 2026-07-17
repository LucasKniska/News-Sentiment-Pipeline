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
    return psycopg.connect()


def upsert_articles(conn: psycopg.Connection, rows: list[dict]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, rows)
