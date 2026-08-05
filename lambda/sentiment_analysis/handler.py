import logging
from datetime import date

from run import run

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    event = event or {}
    # Optional ISO date to target a specific day instead of run()'s "yesterday"
    # default - same override local_run.py exposes for repeatable testing.
    target_date = date.fromisoformat(event["target_date"]) if event.get("target_date") else None

    signal_counts = run(target_date)

    return {"statusCode": 200, "signalCounts": signal_counts}
