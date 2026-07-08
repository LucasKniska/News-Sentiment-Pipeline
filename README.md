# News-Sentiment-Pipeline

Stack: Postgres (RDS) · Terraform · LangChain · Databricks · Datadog · CI/CD (GitHub Actions)

---

## Week 1–2: Infra + schema + CI/CD skeleton

**Terraform / infra**
- [ ] Provision RDS Postgres instance via Terraform
- [ ] Security groups (only allow ingestion service + your IP)
- [ ] IAM roles for Lambda/ECS ingestion service
- [ ] Terraform state stored remotely (S3 backend + lock table)

**Schema / migrations**
- [ ] `articles` table (raw ingested text, `source_id` unique constraint for dedup)
- [ ] `signals` table (`ticker`, `timestamp`, `event_type`, `sentiment`, `confidence`)
- [ ] `daily_returns` table (for backtest output later)
- [ ] Migration tool set up (Alembic or Flyway) — first migration committed

**CI/CD**
- [ ] GitHub Actions: run lint + tests on PR
- [ ] GitHub Actions: `terraform plan` on PR, `terraform apply` on merge
- [ ] CI check that fails if a schema change ships without a migration

**Ingestion**
- [ ] Pick a news source (Alpha Vantage News Sentiment / Finnhub / NewsAPI)
- [ ] Basic ingestion Lambda pulling articles into `articles` table
- [ ] `INSERT ... ON CONFLICT (source_id) DO NOTHING` for idempotent dedup

---

## Week 3–4: LangChain extraction + first observability

**LangChain**
- [ ] Structured-output chain (Pydantic schema: ticker, event_type, sentiment, confidence)
- [ ] Handle hallucinated/invalid tickers (validate against a known ticker list)
- [ ] Write extracted signals into `signals` table
- [ ] Golden-file test set: known articles → expected extraction output

**Datadog**
- [ ] Install Datadog agent / integration
- [ ] Dashboard: ingestion volume, ingestion lag
- [ ] Dashboard: LangChain error rate / parse failure rate
- [ ] Dashboard: RDS connection count, query latency

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

## Week 7: Harden everything

- [ ] Add indexes based on real query patterns from the backtest job (composite index on `(ticker, timestamp)`)
- [ ] `EXPLAIN ANALYZE` before/after — document the improvement
- [ ] Expand CI/CD: block merge if tests fail, add ingestion idempotency test
- [ ] Datadog alerting: ingestion lag threshold, LangChain error rate threshold, RDS throttling/connection threshold
- [ ] Load-test or at least sanity-check ingestion under a burst of articles

---

## Week 8: Polish + writeup

- [ ] Architecture diagram in the README
- [ ] Document the DynamoDB-vs-Postgres decision as a tradeoff section
- [ ] Write up backtest results honestly (including if the signal *didn't* beat cost of turnover)
- [ ] Clean up repo structure, add setup instructions
- [ ] Record a short demo (screen recording or GIF) of the dashboard + a sample query

---

## Notes
- If running behind schedule, compress **Week 7** first — it's the busiest week but the least foundational. Don't compress Weeks 1–2; a shaky foundation compounds.
- Weeks 5–6 are intentionally Databricks-only — built-in slack in case the join/backtest logic takes longer than expected.
