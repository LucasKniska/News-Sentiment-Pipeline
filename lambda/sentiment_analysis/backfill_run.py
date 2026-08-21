import sys
from datetime import date, datetime

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character article text may contain (e.g. currency symbols).
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from run import (
    run_backfill,
)  # noqa: E402  (must import after load_dotenv - schema.py reads TICKERS at import time)


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 2:
        print("Usage: backfill_run.py start_date YYYY-MM-DD end_date YYYY-MM-DD")
        sys.exit(1)

    start_date = _parse_date(args[0])
    end_date = _parse_date(args[1])

    # No get_remaining_ms here - a local run isn't Lambda-time-boxed, so it
    # just works the whole range until it's complete or a date's quota is
    # exhausted (same stopping logic the deployed Lambda uses).
    print(run_backfill(start_date, end_date))
