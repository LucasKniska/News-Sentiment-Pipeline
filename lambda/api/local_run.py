import json
import sys

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character a headline may contain.
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from handler import lambda_handler  # noqa: E402  (must import after load_dotenv)

if __name__ == "__main__":
    args = sys.argv[1:]
    event = {"queryStringParameters": {"limit": args[0]}} if args else {}

    result = lambda_handler(event, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
