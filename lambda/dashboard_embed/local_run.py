import json
import sys

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character the response may contain.
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from handler import lambda_handler  # noqa: E402  (must import after load_dotenv)

if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
