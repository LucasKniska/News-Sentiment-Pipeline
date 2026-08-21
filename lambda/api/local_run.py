import json
import sys

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character a headline may contain.
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from handler import lambda_handler  # noqa: E402  (must import after load_dotenv)

if __name__ == "__main__":
    # local_run.py [limit] [ticker]
    args = sys.argv[1:]
    query_params = {}
    if len(args) >= 1:
        query_params["limit"] = args[0]
    if len(args) >= 2:
        query_params["ticker"] = args[1]
    event = {"queryStringParameters": query_params} if query_params else {}

    result = lambda_handler(event, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
