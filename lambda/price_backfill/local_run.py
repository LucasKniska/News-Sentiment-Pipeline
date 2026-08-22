import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from db import (
    get_connection,
    upsert_daily_prices,
)  # noqa: E402  (must import after load_dotenv)
from transform import to_price_rows  # noqa: E402
from yfinance_client import fetch_price_history  # noqa: E402

DEFAULT_LOOKBACK_DAYS = 365


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(
            "Usage: local_run.py TICKER [start_date YYYY-MM-DD] [end_date YYYY-MM-DD]"
        )
        sys.exit(1)

    ticker = args[0]
    end_date = _parse_date(args[2]) if len(args) > 2 else date.today()
    start_date = (
        _parse_date(args[1])
        if len(args) > 1
        else end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    )

    history = fetch_price_history(ticker, start_date, end_date)
    rows = to_price_rows(ticker, history)

    conn = get_connection()
    try:
        with conn.transaction():
            upsert_daily_prices(conn, rows)
    finally:
        conn.close()

    print(
        f"Upserted {len(rows)} daily_prices rows for {ticker} ({start_date} to {end_date})"
    )
