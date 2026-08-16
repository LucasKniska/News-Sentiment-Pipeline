# Task: July sentiment backfill (now automated)

## Context

`daily_prices` was backfilled for all 5 tracked tickers (NVDA, LMT, XOM, AUR,
AAPL) back to 2026-07-01. `articles` also has real article data back to
2026-07-01 for all five. But `article_sentiment`/`signals` (the LLM
extraction output) only has real coverage for 2026-08-01 through 2026-08-08,
plus 2026-07-01 through 2026-07-06 from a partial backfill run.
**2026-07-07 through 2026-07-31 have never been sentiment-processed.**

This matters for `lambda/sentiment_analysis/price_correlation.py` (correlates
AI sentiment direction against actual daily price direction) - more days
with both sentiment and price data means a less noisy sample.

## How it's being backfilled now

This used to be a manual Git Bash loop, watched by a human for Groq's
account-wide daily token quota (TPD) getting exhausted. It's now automated:
`terraform/schedule.tf`'s `aws_scheduler_schedule.sentiment_backfill_daily`
invokes the deployed `sentiment_analysis` Lambda every morning at 5am ET
(one hour after the live daily run) with a fixed
`{"backfill_range": ["2026-07-07", "2026-07-31"]}` event.
`run_backfill()` (`lambda/sentiment_analysis/run.py`) figures out which dates
in that range still have unprocessed articles (same DB-derived "what's new"
check `run()` already uses for same-day resumability - no separate progress
table), works forward through them, and stops itself once a date shows a
partial extraction failure (the signal that the day's Groq quota is
exhausted) rather than grinding through the rest of the range with doomed
API calls. Nothing needs to run locally or stay logged in for this to make
progress - it runs entirely in AWS.

## Checking progress

```bash
cd lambda/sentiment_analysis
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from db import get_connection
conn = get_connection()
with conn.cursor() as cur:
    cur.execute('''
        SELECT a.datetime::date AS d, count(distinct s.article_id)
        FROM article_sentiment s JOIN articles a ON a.id = s.article_id
        WHERE a.datetime::date BETWEEN '2026-07-07' AND '2026-07-31'
        GROUP BY d ORDER BY d
    ''')
    for row in cur.fetchall():
        print(row)
conn.close()
"
```

You can also check CloudWatch Logs (Console viewer - `aws logs tail` is
currently broken on this machine, see CLAUDE.md) for the
`news-sentiment-analysis` function around 5am ET to see each morning's
`run_backfill` invocation and its stopping reason
(`complete` / `stopped_quota_exhausted` / `stopped_low_on_time`).

To force a run without waiting for the cron:
```bash
# payload.json: {"backfill_range": ["2026-07-07", "2026-07-31"]}
aws lambda invoke --function-name news-sentiment-analysis \
  --cli-binary-format raw-in-base64-out --payload file://payload.json \
  response.json --profile terraform-user --region us-east-1
```

## When the range is fully backfilled

**IMPORTANT - this leaves temporary infrastructure running that must be
manually removed once the 25-day range shows full coverage:**

1. Confirm every date 2026-07-07 through 2026-07-31 shows a non-zero count in
   the query above for all 5 tickers.
2. Delete the `aws_scheduler_schedule.sentiment_backfill_daily` resource from
   `terraform/schedule.tf` (it's marked `TEMPORARY` in a comment there) and
   run `terraform apply` from `terraform/` to remove it - there's no reason
   to keep invoking the Lambda every morning once there's nothing left to
   backfill.
3. Delete this file (`RESUME_SENTIMENT_BACKFILL.md`) - it's a one-off task
   note, not permanent project documentation.
4. Re-run the correlation check to confirm the larger sample:
   ```bash
   cd lambda/sentiment_analysis
   uv run python price_correlation.py --horizon 0
   ```
