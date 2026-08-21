import csv
import sys
from pathlib import Path

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character article text may contain (e.g. currency symbols).
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from db import (
    get_connection,
)  # noqa: E402  (must import after load_dotenv, see local_run.py)

_TICKER = "AAPL"
_SAMPLE_SIZE = 20

# AAPL isn't in TRACKED_TICKERS (schema.py) - this eval set is for hand-rating
# and later comparing against the chain's output, independent of which tickers
# the pipeline currently tracks.
_SELECT_RANDOM_SQL = """
    SELECT id, headline, url, datetime, text
    FROM articles
    WHERE %(ticker)s = ANY(tickers)
      AND text IS NOT NULL
    ORDER BY random()
    LIMIT %(sample_size)s
"""

_OUT_PATH = Path(__file__).parent / "eval" / "eval_set.csv"
_FIELDNAMES = ["id", "headline", "url", "datetime", "text", "human_sentiment", "notes"]


def build() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                _SELECT_RANDOM_SQL, {"ticker": _TICKER, "sample_size": _SAMPLE_SIZE}
            )
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()

    _OUT_PATH.parent.mkdir(exist_ok=True)
    with open(_OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "human_sentiment": "", "notes": ""})

    print(f"Wrote {len(rows)} candidate articles to {_OUT_PATH}")


if __name__ == "__main__":
    build()
