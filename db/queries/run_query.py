import sys

from dotenv import load_dotenv

load_dotenv("lambda/news_ingestion/.env")

import psycopg  # noqa: E402  (must import after load_dotenv)


def main():
    if len(sys.argv) != 2:
        print("Usage: uv run python db/queries/run_query.py <path/to/query.sql>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        sql = f.read()

    conn = psycopg.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            if cur.description:
                for row in cur.fetchall():
                    print(row)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
