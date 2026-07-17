# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

News-Sentiment-Pipeline is a hands-on, self-directed portfolio project. Goal: demonstrate backend/data/infra engineering depth (not frontend) for backend/data/infra-adjacent job applications. Pipeline concept: ingest financial news → extract ticker/sentiment signals with LangChain → join against historical price data in Databricks → backtest → serve results via a small API + website.

Target stack (per README.md, the plan of record): Postgres (RDS) · Terraform · LangChain · Databricks · Lambda + API Gateway · Datadog · GitHub Actions CI/CD.

README.md contains the full week-by-week (currently Week 1–9) build plan with checkboxes — treat it as the up-to-date roadmap and check it for what's done vs. planned before assuming scope.

## Current state

Infra foundation + a first ingestion Lambda scaffold exist; still no LangChain extraction, no Databricks job, no API, no CI/CD, no migration tool.

Python dependency management is `uv`-based: a root-level `pyproject.toml` + `uv.lock` (single shared `.venv` for all Python/Lambda code, per the single-component convention below). There's still only one Python component (`lambda/news_ingestion/`), so all deps (including scraping deps only that component uses) live in one flat dependency list — revisit splitting into uv dependency groups once a second component with different deps shows up (e.g. a Databricks/LangChain step). `lambda/news_ingestion/requirements.txt` (used for the Lambda zip) is a generated artifact — regenerate it with the command below after any dependency change, never hand-edit it. Note: `trafilatura` pulls in `lxml`, a compiled C-extension; there's no Lambda packaging/build step in this repo yet at all, so cross-compiling for Lambda's Linux runtime from this Windows dev machine is an unsolved problem to pick up whenever that packaging step actually gets built.

`db/schema.sql` defines the `articles` table (`id, headline, text, url, datetime, tickers, ingested_at`) and has been applied to the live RDS instance. `id` is Finnhub's article id, doubling as the dedup/`source_id` key the README's Week 1–2 plan calls for. `handler.py` now writes to it on every invocation via `db.py`'s `upsert_articles`: `ON CONFLICT (id) DO UPDATE` merges the incoming `tickers` into the existing array (deduplicated union) rather than discarding the row — necessary because the same article can be fetched under multiple tickers, and `related` only ever echoes the ticker that was queried, so merging is the only way an article's `tickers` array reflects more than one ticker. Schema changes still go through `db/schema.sql` + a manual `psql`/`psycopg` run, not a migration tool or Terraform (Terraform's Postgres provider has no clean way to do arbitrary table DDL).

`terraform/` (AWS CLI profile `terraform-user`, region `us-east-1`, local state) provisions:
- `vpc.tf` — data-source lookups (not resources) against the account's pre-existing default VPC and its subnets. No custom VPC/subnets are created here.
- `rds.tf` — one `db.t3.micro` Postgres 16 RDS instance (`news_sentiment` db, single-AZ, 20GB), a DB subnet group, and a security group on port 5432 scoped to the operator's current public IP, auto-detected via a `data "http"` lookup (`checkip.amazonaws.com`) rather than a hardcoded CIDR — this was changed because the repo is public and the user's IP changes across locations; re-run `terraform apply` after switching networks to refresh the SG rule. `publicly_accessible = true` is deliberate for now (direct `psql` access from the user's laptop) — flagged to revisit once a Lambda can reach RDS privately from inside the VPC.
- `variables.tf` (gitignored, not tracked in git) — holds `db_username`/`db_password` as variable defaults. Never move real credentials into a tracked `.tf` file.
- Terraform state is local (`terraform.tfstate`, gitignored) — not yet migrated to the S3+lock-table remote backend the README's Week 1–2 plan calls for.

`lambda/news_ingestion/` — Finnhub news ingestion scaffold, chosen over NewsAPI.org/Alpha Vantage (see project history for the tradeoff):
- `finnhub_client.py` — thin wrapper around `finnhub.Client`, `fetch_company_news(client, ticker, from_date, to_date)`.
- `scraper.py` — `fetch_article_text(url)` fetches and extracts full article text via `trafilatura`. Best-effort: paywalled/bot-blocked sites are expected to fail often, logs a warning and returns `None` rather than raising.
- `transform.py` — `to_article_row(article, text)`, a pure mapping (no I/O) from a raw Finnhub article dict + scraped text into the `articles` table row shape. Falls back to Finnhub's `summary` field for `text` when scraping fails, and parses the comma-separated `related` field into a `tickers` list.
- `db.py` — `get_connection()` (bare `psycopg.connect()`, reads standard `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD` env vars automatically, no custom config code) and `upsert_articles(conn, rows)` (the `ON CONFLICT ... DO UPDATE` merge described above).
- `handler.py` — `lambda_handler(event, context)`, entry point `handler.lambda_handler`. Reads `tickers` from the event, falling back to `DEFAULT_TICKERS` (currently a small hand-trimmed list, intentionally cut down from the original ~100-ticker S&P-100-ish snapshot for faster local runs — expand it back out if a full-universe run is ever needed) when the event omits `tickers` entirely. Per ticker: fetches news, scrapes each article's `url`, transforms, and upserts into `articles` — one DB transaction per ticker, so one ticker's failure doesn't roll back the others. Only the Finnhub fetch call is caught per-ticker (logged, skipped); a DB-layer failure (e.g. missing table, dropped connection) is deliberately left to propagate and abort the whole run rather than being silently swallowed 100 times over. Flat layout (no package nesting) so this directory's contents zip directly as the Lambda deployment package.
- There is no deployed AWS Lambda anywhere in this project (no Terraform Lambda resource exists yet) — `lambda_handler` is only ever invoked locally via `local_run.py` today.
- `local_run.py` — runs `lambda_handler` locally. `uv run python lambda/news_ingestion/local_run.py` (no args) hits just `["AAPL"]` for a fast smoke test; `... local_run.py all` omits the `tickers` key entirely so it falls back to `DEFAULT_TICKERS`; `... local_run.py MSFT NVDA ...` runs an arbitrary custom list. A full `DEFAULT_TICKERS` run does real web scraping + DB writes for every article of every ticker and can take a long time — the `["AAPL"]` smoke test alone pulled 176 articles.
- Gitignored `.env` (real `FINNHUB_API_KEY` + `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD`) is for local testing only; `.env.example` is the committed placeholder template — never put real values in `.env.example`.

## Commands

- `cd terraform && terraform init` / `terraform plan` / `terraform apply` — standard Terraform workflow, using the `terraform-user` AWS CLI profile.
- `uv sync` (from repo root) — creates/updates the root `.venv` from `pyproject.toml`/`uv.lock`. Run this instead of manually creating a venv or `pip install`-ing.
- `uv add <package>` — add a new Python dependency (updates `pyproject.toml` + `uv.lock` + `.venv` in one step); follow with the `uv export` command below to keep the Lambda's `requirements.txt` in sync.
- `uv run python lambda/news_ingestion/local_run.py [all|<TICKER>...]` — run the ingestion pipeline locally (reads `lambda/news_ingestion/.env` for `FINNHUB_API_KEY` and the `PG*` DB vars), scraping + upserting into `articles`. No args = `["AAPL"]` only; `all` = the full `DEFAULT_TICKERS` list; or pass explicit tickers.
- `uv export --no-hashes -o lambda/news_ingestion/requirements.txt` — regenerate the Lambda deployment `requirements.txt` from `uv.lock`; re-run after any dependency change, never hand-edit that file.
- Applying/updating `db/schema.sql` against the live RDS instance: either `psql -h <rds endpoint> -U <db_username> -d news_sentiment -f db/schema.sql` if `psql` is installed, or run it via `psycopg` (no `psql` client needed — see `db.py`'s `get_connection()` for the connection pattern) — endpoint via `terraform output rds_endpoint`, credentials from `terraform/variables.tf`.
- No lint/test commands exist yet.

## Working conventions for this project

- This is a learning project: the user owns architecture-level decisions and generally wants hands-on AWS/Terraform steps explained as a tutorial rather than executed directly on their behalf. Plain boilerplate (CLI installs, `.gitignore` edits, formatting) is fine to just do.
- Default to building the smallest next coherent piece and confirming before expanding, even when a request names multiple resources at once (e.g. "DB + 2 Lambdas") — sequence it instead of scaffolding it all in one pass.
- Before adding new Terraform (or other infra-as-code), check what already exists in `terraform/` rather than assuming a clean slate.
- Two architecture decisions are intentionally still open — surface them again before extending infra rather than assuming an answer: (1) whether to keep RDS `publicly_accessible = true` or move to private-subnet access once a Lambda exists; (2) whether to introduce custom private subnets or keep using the default VPC's public subnets.
- Do not create pushes or new worktrees unless specifically prompted. Creating a new branch and committing to it is fine — just do not push it.
- All Python dependencies for a component go into a single `requirements.txt`, whether needed for dev or production — no separate `requirements-dev.txt` split.
