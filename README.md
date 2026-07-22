# News-Sentiment-Pipeline

A data/backend/infra engineering portfolio project: a pipeline that turns financial news into a tradeable signal, and honestly measures whether that signal is worth anything.

**This project is not finished.** This README describes where it's headed. For what's actually built so far, see [TODO.md](TODO.md).

## What it does

1. **Ingest** financial news for a universe of tickers from a news API.
2. **Extract** structured signals from each article with LangChain — ticker, event type, sentiment score, confidence — validated against Pydantic schemas so hallucinated tickers or malformed output get caught, not silently stored.
3. **Join** those signals against historical price data in Databricks to compute forward returns (next 1-day, next 5-day) for each article's ticker.
4. **Backtest** by bucketing articles into sentiment quintiles and comparing average forward return per bucket — the core question the project exists to answer: does sentiment extracted this way actually predict price movement, net of noise?
5. **Serve** the results — both the nightly backtest output and on-demand per-ticker signal history — through a small API (API Gateway + Lambda) and a minimal website, rather than leaving results stranded in a notebook.

## Why this exists

It's a self-directed exercise in building the kind of system a backend/data/infra role actually owns end to end: provisioned infrastructure (Terraform), a real database schema that evolves under real constraints, a scheduled data pipeline, an LLM-extraction step treated as an unreliable external dependency (validated, tested, monitored — not trusted blindly), a batch analytics job, and a small API in front of all of it. Frontend work is intentionally minimal; the depth is meant to show in the infra and data layers.

## Target stack

Postgres (RDS) · Terraform · LangChain · Databricks · Lambda + API Gateway · Datadog · GitHub Actions CI/CD

## Design principles

- **Idempotent ingestion.** The same article can be fetched multiple times (once per ticker it's related to); ingestion is built to merge, not duplicate.
- **Untrusted LLM output.** Sentiment/ticker/event-type extraction is validated against known-good schemas and a real ticker list before it's trusted enough to write to the database.
- **Honest backtesting.** The end goal is a real answer, including the possibility that the signal doesn't beat the cost of turnover — that result gets written up too, not hidden.
- **Observability from the start.** Ingestion lag, extraction error rate, and API latency are meant to be dashboarded and alerted on, not just logged.

## Current state

See [TODO.md](TODO.md) for the week-by-week build plan and what's actually done vs. still planned.
