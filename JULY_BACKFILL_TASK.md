# Task: finish the July news backfill + verify in Postgres

Handoff doc for a fresh session (or a `/goal`) to pick up and finish. Nothing
new needs to be built — the tooling already exists and works; this is just
running it to completion and checking the result. Written 2026-08-09 after a
first backfill attempt was manually stopped partway through.

## What already exists (no code changes needed)

- `lambda/news_ingestion/handler.py`'s `lambda_handler` accepts optional
  `from_date`/`to_date` (ISO strings) in its event dict to target a historical
  day instead of its normal "yesterday" default. When either key is present it
  also skips the `/quote` price fetch (that endpoint has no historical mode —
  historical closes are `lambda/price_backfill`'s job, not this one's).
- `lambda/news_ingestion/backfill_run.py` loops a date range one day at a time,
  calling `lambda_handler` once per day with `from_date == to_date == that day`
  for a fixed ticker list (defaults to `DEFAULT_TICKERS`: NVDA, LMT, XOM, AUR,
  AAPL — same 5 tickers `lambda/sentiment_analysis` tracks). One invocation per
  day is deliberate: `MAX_ARTICLES_PER_TICKER_PER_DAY = 50` in `handler.py` is a
  per-call cap, so calling it once per day is what makes the cap apply
  per-ticker-per-day rather than per-ticker-for-the-whole-range.
- Both are already tested and known to work: a single day (all 5 tickers) takes
  ~3.5 minutes end-to-end (mostly sequential per-article scraping via
  `trafilatura`), so the full 30 remaining days is roughly **1.5-2 hours**.

## Current state of `articles` for July (checked 2026-08-09 via ad-hoc SQL, see below)

- **2026-07-01: complete.** NVDA 49, LMT 14, XOM 17, AUR 1, AAPL 50 — all under
  the 50 cap, all 5 tracked tickers present. This was a full, uninterrupted run.
- **2026-07-02 through 2026-07-07: partial / uncertain.** The backfill job was
  killed mid-run while processing 07-02. `handler.py` commits one DB
  transaction per ticker (not per day), so whatever ticker had finished before
  the kill is already committed, and later tickers/days may be incomplete or
  entirely unprocessed. AUR is notably absent on several of these days — could
  be genuinely zero AUR news that day (07-01/07-06/07-31 each only had 1 AUR
  article all day, so AUR is a low-volume ticker generally) or could mean AUR
  just wasn't reached before the kill. Don't assume either way — re-running is
  the only way to know for sure.
- **2026-07-08 through 2026-07-14: completely missing.** No rows at all.
- **2026-07-15 through 2026-07-18: has data, but not from this backfill effort
  and not fully explained.** Rows exist for GOOGL and MSFT — tickers that
  aren't in `DEFAULT_TICKERS`/`TRACKED_TICKERS` at all — with counts well over
  the 50 cap (105, 102, 97, 199 on 07-15/07-16 alone). This is very likely
  leftover data from an earlier, unrelated manual/exploratory run (predating
  the 50-article cap and/or the current tracked-ticker list) rather than
  anything this backfill wrote. **Flag this to the user before touching it** —
  don't assume it's safe to overwrite or that it needs to be backfilled to
  match the cap; it may be intentionally-kept data from other work.
- **2026-07-19 through 2026-07-30: completely missing.** No rows at all.
- **2026-07-31: partial, from a different source.** NVDA 159, XOM 53, LMT 4,
  AUR 1 — no AAPL, and NVDA/XOM are both way over the 50 cap. This is almost
  certainly the scheduled ingestion Lambda's very first live run (it started
  2026-08-01 per `terraform/schedule.tf`, and `handler.py`'s normal/live path
  is `from_date = today - 1 day`, so its first invocation on 08-01 would have
  pulled 07-31's news) — again, not something this backfill effort produced.

**Bottom line: only 07-01 is a known-good, fully-capped backfill day.** Every
other day in July needs the backfill (re-)run against it. Because
`upsert_articles` does `ON CONFLICT (id) DO UPDATE` (merging `tickers`, not
overwriting), re-running an already-partially-filled day is safe/idempotent —
it will not create duplicates or lose data, it just fills in whatever's
missing. It's fine to just re-run the whole 07-02 through 07-31 range,
including the anomalous 07-15/07-16/07-31 days — the merge behavior means
existing rows just get more tickers added if applicable, not replaced.

## Steps to finish

1. **Run the backfill for the remaining range** (repo root):
   ```
   uv run python lambda/news_ingestion/backfill_run.py 2026-07-02 2026-07-31
   ```
   This will take ~1.5-2 hours. Run it in the background and let it finish —
   don't split it into smaller chunks unless there's a reason to check
   progress partway. Uses `lambda/news_ingestion/.env` for `FINNHUB_API_KEY`
   and `PG*` DB creds (already set up, same file the smoke tests used).

2. **Verify via SQL** once the run completes — this was the step never reached
   last time. Use `db/queries/run_query.py` with a query like:
   ```sql
   SELECT date_trunc('day', datetime)::date AS day, unnest(tickers) AS ticker, count(*)
   FROM articles
   WHERE datetime >= '2026-07-01' AND datetime < '2026-08-01'
   GROUP BY 1, 2
   ORDER BY 1, 2;
   ```
   Confirm every day 07-01 through 07-31 has a row for each of NVDA, LMT, XOM,
   AUR, AAPL (AUR may legitimately be absent on some days — it's a low-volume
   ticker; don't treat that alone as a failure). Flag anything that still looks
   wrong (a day with zero rows for every ticker, a count still at/near a
   suspicious multiple of 50 suggesting a second uncapped source wrote there,
   etc.) rather than declaring done.

3. Mention the 07-15/07-16/07-31 anomaly (GOOGL/MSFT rows, over-cap counts) to
   the user rather than silently leaving or fixing it — it predates this task
   and its origin isn't confirmed.

## Explicitly out of scope for this task

- No sentiment/`signals` extraction for July — that's a separate step
  (`lambda/sentiment_analysis/run.py`, one `target_date` at a time) that only
  makes sense to run after articles exist, and wasn't part of the original ask.
- No price backfill — `daily_prices` for July is already handled separately by
  `lambda/price_backfill` (see `TODO.md`, already checked off).
- No code changes — `handler.py` and `backfill_run.py` already support this;
  don't add anything new unless the run surfaces an actual bug.
