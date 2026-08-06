# TODO

Week-by-week build plan and current status. See [README.md](README.md) for what this project is and where it's headed.

---

## Week 1–2: Infra + schema + CI/CD skeleton

**Terraform / infra**
- [x] Provision RDS Postgres instance via Terraform
- [ ] Security groups (only allow ingestion service + your IP) — currently scoped to just the operator's IP
- [x] IAM roles for Lambda/ECS ingestion service — `aws_iam_role` + inline `rds-db:connect` policy for the ingestion Lambda (`terraform/lambda.tf`)
- [x] IAM role + Terraform-deployed Lambda for the `sentiment_analysis` component, scheduled daily via EventBridge Scheduler alongside ingestion (`terraform/sentiment_lambda.tf`, `terraform/schedule.tf`)
- [ ] Terraform state stored remotely (S3 backend + lock table) — still local state

**Schema / migrations**
- [x] `articles` table (`id, headline, text, url, datetime, tickers, ingested_at`) — applied to the live RDS instance via `db/schema.sql`; Finnhub's article `id` doubles as the dedup key
- [x] `signals` table — one row per sentiment-calculation *run* for a ticker (not per article): `ticker`, `timestamp` (when the run executed), `event_type` (single dominant value), `sentiment` (numeric, so later quintile bucketing is possible), `involvement`, `article_ids` (every article the run aggregated over). Append-only — reruns later the same day insert a new row rather than overwriting, preserving intraday history. Table created via `db/schema.sql`
- [ ] ~~`daily_returns` table (for backtest output later)~~
- [ ] ~~Migration tool (Alembic or Flyway)~~ — deliberate non-goal; the plain `db/schema.sql` + `run_query.py` script has handled two table additions fine

**CI/CD**
- [ ] GitHub Actions: run lint + tests on PR
- [ ] GitHub Actions: `terraform plan` on PR, `terraform apply` on merge
- [ ] CI check that fails if a schema change ships without a migration

**Ingestion**
- [x] Pick a news source (Alpha Vantage News Sentiment / Finnhub / NewsAPI) — Finnhub
- [x] Basic ingestion pulling articles into `articles` table — `lambda_handler` in `lambda/news_ingestion/handler.py` fetches, scrapes full article text (`trafilatura`, falling back to Finnhub's `summary`), and upserts into `articles`
- [x] `INSERT ... ON CONFLICT (id) DO UPDATE` merging `tickers` across duplicate fetches for idempotent dedup — chosen over plain `DO NOTHING` since the same article can come back under multiple tickers' fetches
- [x] Deploy ingestion as an actual AWS Lambda via Terraform (IAM DB auth to RDS, no VPC attachment)
- [x] Schedule/trigger for the Lambda — daily EventBridge cron (`terraform/schedule.tf`)

---

## Week 3–4: LangChain extraction

**LangChain**
- [x] Structured-output chain (Pydantic schema: ticker, event_type, sentiment, involvement) — `chain.py` + `combine_chain.py`
- [x] Handle hallucinated/invalid tickers (validate against a known ticker list) — `schema.py`'s `Literal[TRACKED_TICKERS]`
- [x] Write extracted signals into `signals` table — `db.py`/`run.py`
- [x] Golden-file test set: known articles → expected extraction output — `build_eval_set.py` + hand-rated `eval_set.csv` + `run_eval.py`

---

## Week 5–6: Databricks join + backtest

**Databricks**
- [ ] Databricks job reads `signals` + `articles` from Postgres via JDBC
- [ ] Pull historical price data (yfinance / Polygon) for relevant tickers
- [ ] Join signals to forward returns (next 1-day, next 5-day)
- [ ] Backtest: bucket by sentiment quintile, compare average forward return per bucket
- [ ] Write backtest output to `daily_returns` table
- [ ] Schedule job to run nightly

---

## Week 7: API + website

**Backend API**
- [ ] SQS queue + DLQ (redrive policy, max receive count) provisioned via Terraform for the ingestion → sentiment-analysis handoff
- [ ] API Gateway + Lambda serving JSON endpoints over `signals` / `daily_returns` (`GET /backtest`, `GET /tickers/{ticker}`, `GET /signals/recent`)
- [ ] IAM role + security group for the API Lambda to reach RDS
- [ ] Query-param filtering (ticker, date range)

**Frontend**
- [ ] Minimal site (server-rendered pages or static page) hitting the API — replaces the Databricks notebook as the way results get viewed
- [ ] Deploy via Terraform (S3 + CloudFront if static, or served from the same Lambda)

**Note:** this also creates a second query pattern (on-demand ticker lookups from the website, vs. the nightly Databricks batch scan) — feed both into the indexing work below.

---

## Week 8: Harden everything

- [ ] Add indexes based on real query patterns from both the nightly backtest job and the website's on-demand ticker lookups (composite index on `(ticker, timestamp)`)
- [ ] `EXPLAIN ANALYZE` before/after — document the improvement
- [ ] Expand CI/CD: block merge if tests fail, add ingestion idempotency test
- [ ] Load-test or at least sanity-check ingestion under a burst of articles

---

## Week 9: Polish + writeup

- [ ] Architecture diagram in the README
- [ ] Document the DynamoDB-vs-Postgres decision as a tradeoff section
- [ ] Write up backtest results honestly (including if the signal *didn't* beat cost of turnover)
- [ ] Clean up repo structure, add setup instructions
- [ ] Record a short demo (screen recording or GIF) of the website + a sample query

---

## Notes
- If running behind schedule, compress **Week 8** first — it's the busiest week but the least foundational. Don't compress Weeks 1–2; a shaky foundation compounds.
- Weeks 5–6 are intentionally Databricks-only — built-in slack in case the join/backtest logic takes longer than expected.
