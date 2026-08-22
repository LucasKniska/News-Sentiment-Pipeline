import logging
from datetime import date

from run import run, run_backfill

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    event = event or {}

    # backfill_range = [start_iso, end_iso]: works forward through a fixed date
    # range across repeated invocations (see run_backfill's docstring/comment in
    # run.py) instead of run()'s single-date behavior - used by the temporary
    # sentiment_backfill_daily EventBridge schedule (terraform/schedule.tf).
    if "backfill_range" in event:
        start_date, end_date = (date.fromisoformat(d) for d in event["backfill_range"])
        return run_backfill(start_date, end_date, context.get_remaining_time_in_millis)

    # Optional ISO date to target a specific day instead of run()'s "yesterday"
    # default - same override local_run.py exposes for repeatable testing.
    target_date = (
        date.fromisoformat(event["target_date"]) if event.get("target_date") else None
    )

    stats = run(target_date)

    return {"statusCode": 200, "signalCounts": stats["signal_counts"]}
