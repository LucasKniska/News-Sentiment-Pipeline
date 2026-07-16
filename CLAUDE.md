# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

News-Sentiment-Pipeline is a hands-on, self-directed portfolio project. Goal: demonstrate backend/data/infra engineering depth (not frontend) for backend/data/infra-adjacent job applications. Pipeline concept: ingest financial news → extract ticker/sentiment signals with LangChain → join against historical price data in Databricks → backtest → serve results via a small API + website.

Target stack (per README.md, the plan of record): Postgres (RDS) · Terraform · LangChain · Databricks · Lambda + API Gateway · Datadog · GitHub Actions CI/CD.

README.md contains the full week-by-week (currently Week 1–9) build plan with checkboxes — treat it as the up-to-date roadmap and check it for what's done vs. planned before assuming scope.

## Current state

Infra foundation + a first ingestion Lambda scaffold exist; still no LangChain extraction, no Databricks job, no API, no CI/CD, no DB schema/migrations.

`terraform/` (AWS CLI profile `terraform-user`, region `us-east-1`, local state) provisions:
- `vpc.tf` — data-source lookups (not resources) against the account's pre-existing default VPC and its subnets. No custom VPC/subnets are created here.
- `rds.tf` — one `db.t3.micro` Postgres 16 RDS instance (`news_sentiment` db, single-AZ, 20GB), a DB subnet group, and a security group on port 5432 scoped to the operator's current public IP, auto-detected via a `data "http"` lookup (`checkip.amazonaws.com`) rather than a hardcoded CIDR — this was changed because the repo is public and the user's IP changes across locations; re-run `terraform apply` after switching networks to refresh the SG rule. `publicly_accessible = true` is deliberate for now (direct `psql` access from the user's laptop) — flagged to revisit once a Lambda can reach RDS privately from inside the VPC.
- `variables.tf` (gitignored, not tracked in git) — holds `db_username`/`db_password` as variable defaults. Never move real credentials into a tracked `.tf` file.
- Terraform state is local (`terraform.tfstate`, gitignored) — not yet migrated to the S3+lock-table remote backend the README's Week 1–2 plan calls for.

`lambda/news_ingestion/` — Finnhub news ingestion scaffold, chosen over NewsAPI.org/Alpha Vantage (see project history for the tradeoff):
- `finnhub_client.py` — thin wrapper around `finnhub.Client`, `fetch_company_news(client, ticker, from_date, to_date)`.
- `handler.py` — `lambda_handler(event, context)`, entry point `handler.lambda_handler`. Reads `tickers` from the event (default `["AAPL"]`), pulls the last day of company news per ticker. Flat layout (no package nesting) so this directory's contents zip directly as the Lambda deployment package.
- No DB write/dedup yet — lands once the `articles` table exists (Week 1–2 roadmap).
- `local_run.py` + gitignored `.env` (real `FINNHUB_API_KEY`) are for local testing only; `.env.example` is the committed placeholder template — never put a real key in `.env.example`.

## Commands

- `cd terraform && terraform init` / `terraform plan` / `terraform apply` — standard Terraform workflow, using the `terraform-user` AWS CLI profile.
- Root-level `.venv` runs the Python/Lambda code: `python -m venv .venv`, then `source .venv/Scripts/activate` (Windows) and `pip install -r lambda/news_ingestion/requirements.txt`.
- No lint/test commands exist yet.

## Working conventions for this project

- This is a learning project: the user owns architecture-level decisions and generally wants hands-on AWS/Terraform steps explained as a tutorial rather than executed directly on their behalf. Plain boilerplate (CLI installs, `.gitignore` edits, formatting) is fine to just do.
- Default to building the smallest next coherent piece and confirming before expanding, even when a request names multiple resources at once (e.g. "DB + 2 Lambdas") — sequence it instead of scaffolding it all in one pass.
- Before adding new Terraform (or other infra-as-code), check what already exists in `terraform/` rather than assuming a clean slate.
- Two architecture decisions are intentionally still open — surface them again before extending infra rather than assuming an answer: (1) whether to keep RDS `publicly_accessible = true` or move to private-subnet access once a Lambda exists; (2) whether to introduce custom private subnets or keep using the default VPC's public subnets.
- Do not create pushes or new worktrees unless specifically prompted. Creating a new branch and committing to it is fine — just do not push it.
- All Python dependencies for a component go into a single `requirements.txt`, whether needed for dev or production — no separate `requirements-dev.txt` split.
