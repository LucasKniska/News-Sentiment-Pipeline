import json
import logging

from db import fetch_recent_signals, get_connection

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200

# Response is already shaped for an API Gateway Lambda proxy integration
# (statusCode/headers/body) so wiring API Gateway up later doesn't require
# touching this handler again.
_HEADERS = {"Content-Type": "application/json"}


def lambda_handler(event, context):
    event = event or {}
    params = event.get("queryStringParameters") or {}
    try:
        limit = min(int(params.get("limit", _DEFAULT_LIMIT)), _MAX_LIMIT)
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT

    ticker = params.get("ticker")
    if ticker:
        ticker = ticker.upper()

    conn = get_connection()
    try:
        signals = fetch_recent_signals(conn, limit, ticker)
    finally:
        conn.close()

    return {"statusCode": 200, "headers": _HEADERS, "body": json.dumps(signals)}
