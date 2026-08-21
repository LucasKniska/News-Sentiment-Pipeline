import sys
from datetime import date

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character article text may contain (e.g. currency symbols).
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from run import (
    run,
)  # noqa: E402  (must import after load_dotenv - schema.py reads TICKERS at import time)

if __name__ == "__main__":
    # Optional YYYY-MM-DD arg to target a known date instead of run()'s "yesterday"
    # default - useful for repeatable local testing against a date already ingested.
    target_date = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    print(run(target_date))
