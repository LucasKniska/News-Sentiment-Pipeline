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
- [ ] `daily_returns` table (for backtest output later)
- [ ] ~~Migration tool (Alembic or Flyway)~~ — deliberate non-goal; the plain `db/schema.sql` + `run_query.py` script has handled two table additions fine

**CI/CD**
- [x] GitHub Actions: lint on PR (`.github/workflows/ci.yml`) — Python via `black --check`, Terraform via `terraform fmt -check`. Scoped to lint only, not "lint + tests": the only test-shaped scripts (`run_eval.py`, `test_fallback.py`) don't add value running automatically on every PR, so no test job was added.
- [ ] ~~GitHub Actions: `terraform plan` on PR, `terraform apply` on merge~~ — deliberately not doing this; it needs Terraform state stored remotely (S3 backend + lock table, itself still unchecked above) to be safe from a CI runner, and the decision has been made not to migrate state to a remote/cloud backend. `terraform validate` is also skipped in CI for a related reason: `terraform/variables.tf` is gitignored, so it doesn't exist on a fresh CI checkout and every `var.*` reference would fail as undeclared.
- [ ] ~~CI check that fails if a schema change ships without a migration~~ — deliberately not doing this; deferred alongside the item above rather than attempted separately

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

## Week 5: Databricks join + backtest

**Databricks**
- [x] Databricks job reads `signals` + `articles` from Postgres via JDBC
- [x] Pull historical price data (yfinance / Polygon) for relevant tickers
- [ ] Join signals to forward returns (next 1-day, next 5-day)
- [ ] Backtest: bucket by sentiment quintile, compare average forward return per bucket
- [ ] Write backtest output to `daily_returns` table
- [x] Schedule job to run nightly

---

## Week 6: API + website

**Backend API**
- [ ] SQS queue + DLQ (redrive policy, max receive count) provisioned via Terraform for the ingestion → sentiment-analysis handoff
- [x] API Gateway + Lambda serving JSON over `signals` — `GET /signals/recent` deployed via `terraform/api.tf` (2026-08-21). `GET /tickers/{ticker}` dropped as redundant now that `/signals/recent?ticker=` covers it; `GET /backtest` deferred — depends on Week 5's `daily_returns` work, and may end up unnecessary now that the plan is to embed the real Databricks dashboard rather than rebuild backtest charts from raw data.
- [x] IAM role for the API Lambda to reach RDS (IAM DB auth via the `api_read` Postgres role, same pattern as the other two Lambdas — no VPC/security-group attachment needed, matching how `news_ingestion`/`sentiment_analysis` reach RDS)
- [x] Query-param filtering — `ticker` and `limit` on `/signals/recent`; no date-range filter yet
- [x] Rate limiting — API Gateway stage-level throttle (`throttling_rate_limit = 4`, `throttling_burst_limit = 8` req/sec) caps worst-case cost around $12-13/month even under sustained abuse; `reserved_concurrent_executions` was attempted but reverted since this AWS account's total Lambda concurrency limit is only 10

**Frontend**
- [x] Databricks dashboard-embed broker — `GET /dashboard-token` deployed via `terraform/dashboard_embed.tf` (2026-08-21); does the 3-call Databricks OAuth exchange server-side and hands the frontend a short-lived embed token. Service principal's CAN RUN grant verified working end-to-end via a live curl test; the workspace's approved-domains allowlist (for the actual GitHub Pages origin) is set but can only be confirmed once the frontend page below actually loads the embed.
- [ ] Minimal site (static page) hitting both APIs — `/signals/recent` for raw data, `/dashboard-token` + `@databricks/aibi-client` for the embedded dashboard. Plan is GitHub Pages (not S3+CloudFront — no server runtime needed now that the Databricks secret lives in the Lambda broker, not the frontend)
- [ ] Deploy the static site to GitHub Pages

**Note:** this also creates a second query pattern (on-demand ticker lookups from the website, vs. the nightly Databricks batch scan) — feed both into the indexing work below.

---

## Week 7: Harden everything

**Finishing Up**
- [ ] Add indexes based on real query patterns from both the nightly backtest job and the website's on-demand ticker lookups (composite index on `(ticker, timestamp)`)
- [ ] `EXPLAIN ANALYZE` before/after — document the improvement
- [ ] Expand CI/CD: block merge if tests fail, add ingestion idempotency test
- [ ] Load-test or at least sanity-check ingestion under a burst of articles

**Final Writeup**
- [ ] Architecture diagram in the README
- [ ] Document the DynamoDB-vs-Postgres decision as a tradeoff section
- [ ] Write up backtest results honestly (including if the signal *didn't* beat cost of turnover)
- [ ] Clean up repo structure, add setup instructions
- [ ] Record a short demo (screen recording or GIF) of the website + a sample query

---

## Notes
- If running behind schedule, compress **Week 8** first — it's the busiest week but the least foundational. Don't compress Weeks 1–2; a shaky foundation compounds.
- Weeks 5–6 are intentionally Databricks-only — built-in slack in case the join/backtest logic takes longer than expected.
