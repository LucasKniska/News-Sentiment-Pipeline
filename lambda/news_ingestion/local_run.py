import sys

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character scraped article text may contain (e.g. currency symbols).
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from handler import lambda_handler  # noqa: E402  (must import after load_dotenv)

if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["all"]:
        event = {}  # no "tickers" key -> lambda_handler falls back to DEFAULT_TICKERS
    elif args:
        event = {"tickers": args}
    else:
        event = {"tickers": ["AAPL"]}

    result = lambda_handler(event, None)
    for ticker, rows in result["articles"].items():
        for row in rows:
            print(row)
    print(result["articleCounts"])