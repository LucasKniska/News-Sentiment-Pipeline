# Task: resume July sentiment backfill

## Context

`daily_prices` was backfilled for all 5 tracked tickers (NVDA, LMT, XOM, AUR, AAPL)
back to 2026-07-01. `articles` also has real article data back to 2026-07-01 for all
five. But `article_sentiment`/`signals` (the LLM extraction output) only has real
coverage for 2026-08-01 through 2026-08-08, plus 2026-07-01 through 2026-07-06 from a
partial backfill run. **2026-07-07 through 2026-07-31 have never been sentiment-processed.**

This matters for `lambda/sentiment_analysis/price_correlation.py` (correlates AI
sentiment direction against actual daily price direction) - more days with both
sentiment and price data means a less noisy sample. Right now n is ~20 observations,
which the script itself flags as too small to draw conclusions from.

The previous backfill attempt stopped partway through 2026-07-06 because Groq's
**daily** token quota (shared across the whole account, not per-minute) was
exhausted across every model in the fallback ladder
(`llama-3.3-70b-versatile`, `openai/gpt-oss-120b`, `openai/gpt-oss-20b`,
`qwen/qwen3.6-27b` - see `lambda/sentiment_analysis/chain.py`'s
`GROQ_MODELS_BEST_TO_WORST`). The user chose to wait for the quota to reset
(daily) rather than pay for an Anthropic fallback or shrink scope.

## What to run

From the repo root, in Git Bash (the date arithmetic needs GNU `date -d`, not
PowerShell):

```bash
cd lambda/sentiment_analysis
d=2026-07-07
while [ "$d" != "2026-08-01" ]; do
  echo "=== $d ==="
  uv run python local_run.py "$d"
  d=$(date -I -d "$d + 1 day")
done
```

- `local_run.py <date>` calls `run.py`'s `run(target_date)`, which processes **all**
  `TRACKED_TICKERS` for that one date in a single call - do not loop per ticker.
- It's upsert-safe (`ON CONFLICT ... DO UPDATE` in `db.py`) - safe to re-run a date
  that partially succeeded.
- Do not re-run `lambda/price_backfill` - `daily_prices` is already fully backfilled
  to 7/1 for all 5 tickers, this task is sentiment-only.
- Do not touch `db/schema.sql`, Terraform, or any infra - this is a pure data
  backfill using existing scripts.

## Watch for: Groq daily quota exhaustion (again)

Each `local_run.py <date>` call prints per-article model attempts. If you see the
same pattern as before - every one of the 4 Groq models failing with `Error code:
429` and `"tokens per day (TPD)"` in the message, for consecutive articles - the
quota is exhausted again. **Stop the loop at that point rather than letting it grind
through 429s for the rest of July.** Note the last date that actually produced
results (look for a printed dict like `{'AAPL': 12, 'NVDA': 8}` after each date -
that's `run()`'s return value, empty/sparse dict = little or nothing succeeded that
day) and report back which date to resume from next.

## When it finishes (or gets interrupted)

1. Report which dates completed successfully (non-trivial signal counts) vs. which
   hit the rate limit, so a future run knows where to pick up.
2. Re-run the correlation check to confirm the larger sample:
   ```bash
   cd lambda/sentiment_analysis
   uv run python price_correlation.py --horizon 0
   ```
3. Delete this file (`RESUME_SENTIMENT_BACKFILL.md`) once July is fully backfilled -
   it's a one-off task note, not permanent project documentation.

## Optional: verify coverage before/after

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
        GROUP BY d ORDER BY d
    ''')
    for row in cur.fetchall():
        print(row)
conn.close()
"
```
