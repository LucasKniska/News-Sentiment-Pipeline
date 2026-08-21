import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character scraped article text may contain (e.g. currency symbols).
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from handler import (
    DEFAULT_TICKERS,
    lambda_handler,
)  # noqa: E402  (must import after load_dotenv)


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        print(
            "Usage: backfill_run.py start_date YYYY-MM-DD end_date YYYY-MM-DD [TICKER...]"
        )
        sys.exit(1)

    start_date = _parse_date(args[0])
    end_date = _parse_date(args[1])
    tickers = args[2:] or DEFAULT_TICKERS

    day = start_date
    totals = {ticker: 0 for ticker in tickers}
    while day <= end_date:
        # One invocation per day (not one multi-day range) so
        # MAX_ARTICLES_PER_TICKER_PER_DAY caps each day independently rather
        # than the whole range combined.
        event = {
            "tickers": tickers,
            "from_date": day.isoformat(),
            "to_date": day.isoformat(),
        }
        result = lambda_handler(event, None)
        for ticker, count in result["articleCounts"].items():
            totals[ticker] += count
        print(day.isoformat(), result["articleCounts"])
        day += timedelta(days=1)

    print("Totals:", totals)
