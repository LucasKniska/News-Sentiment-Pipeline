# Task: sentiment extraction schema + ticker centralization

Handoff doc for a fresh session to implement. Context: this is the first piece of
Week 3-4 (LangChain extraction) — see TODO.md. Nothing here has been implemented yet;
this file is the full spec agreed on in a prior planning conversation.

## 1. New file: `lambda/sentiment_analysis/schema.py`

New component, mirrors the flat-layout convention of `lambda/news_ingestion/`
(no package nesting — this directory will eventually zip directly as a Lambda
deployment package, same as news_ingestion does).

```python
import os
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# Sourced from the TICKERS env var (see section 2) so this project's scope stays
# in sync with lambda/news_ingestion/handler.py's ticker list — no duplication.
TRACKED_TICKERS = tuple(os.environ.get("TICKERS", "NVDA,LMT,XOM,AUR").split(","))
Ticker = Literal[TRACKED_TICKERS]


class EventType(str, Enum):
    earnings_report = "earnings_report"
    guidance_change = "guidance_change"
    product_or_technology_launch = "product_or_technology_launch"
    contract_award = "contract_award"
    contract_loss_or_cancellation = "contract_loss_or_cancellation"
    mergers_acquisitions = "mergers_acquisitions"
    partnership_or_joint_venture = "partnership_or_joint_venture"
    leadership_change = "leadership_change"
    layoffs_or_restructuring = "layoffs_or_restructuring"
    labor_dispute = "labor_dispute"
    legal_or_regulatory_action = "legal_or_regulatory_action"
    regulatory_approval_or_permit = "regulatory_approval_or_permit"
    export_control_or_trade_policy = "export_control_or_trade_policy"
    supply_chain_disruption = "supply_chain_disruption"
    production_or_capacity_change = "production_or_capacity_change"
    facility_incident_or_outage = "facility_incident_or_outage"
    environmental_or_safety_incident = "environmental_or_safety_incident"
    cybersecurity_incident = "cybersecurity_incident"
    commodity_or_input_price_impact = "commodity_or_input_price_impact"
    capital_return = "capital_return"


class TickerSentiment(BaseModel):
    ticker: Ticker = Field(description="Ticker this sentiment applies to")
    sentiment: float = Field(ge=-1, le=1, description="Sentiment of the article's discussion of this specific ticker, -1 to 1")
    event_type: EventType
    confidence: float = Field(ge=0, le=1, description="Confidence in this ticker's sentiment/event_type call specifically")
    # TODO(cut-before-ship): kept only while calibrating against the eval set so a
    # wrong call can be inspected. Not part of the `signals` table — drop this field
    # once the chain's accuracy/confidence correlation checks out.
    reasoning: str = Field(description="One-sentence justification for the sentiment/event_type call")


class ArticleExtraction(BaseModel):
    ticker_sentiments: list[TickerSentiment] = Field(
        description="One entry per ticker with substantive discussion in the article. Skip tickers only mentioned in passing."
    )
```

Design notes (why it looks like this, in case questioned later):
- **List of per-ticker objects, not one article-level sentiment** — an article can
  have a negative section on one ticker and a positive section on another; each
  needs its own independent sentiment/confidence/event_type.
- **`event_type` is a closed enum, not a free string** — prevents hallucinated/
  inconsistent labels that would break downstream grouping. The 20 values were
  chosen to cover tech/defense/oil (the three tracked industries) at an
  operations/business level — no analyst-rating/price-target-type categories,
  since those are market reactions *to* the company, not something the company did.
- **`Ticker` is constrained to the known universe** — deliberately scoped to only
  the tickers this project signals on, not the open market. Built from an env var
  (see below) instead of hardcoded twice.
- **`reasoning` is temporary** — useful while building the eval set to debug wrong
  calls, but adds output tokens/cost and isn't stored in `signals`. Remove once the
  chain's confidence scores are validated against the eval set.

## 2. Centralize the ticker list via Terraform (currently duplicated in `handler.py`)

Terraform already injects shared config (`FINNHUB_API_KEY`, `PGHOST`, etc.) into
Lambda environments — see `terraform/lambda.tf:76-85`. Extend that same pattern so
the ticker list lives in exactly one place instead of being hardcoded in every
Python component that needs it.

**`terraform/lambda.tf`** — add a `locals` block (near the top, alongside the
existing `lambda_db_username` local):
```hcl
locals {
  # Single source of truth for which tickers this project tracks/signals on.
  # Passed to every Lambda via TICKERS so ingestion and sentiment extraction
  # can't drift out of sync.
  tracked_tickers = ["NVDA", "LMT", "XOM", "AUR"]
}
```

Then add to `aws_lambda_function.news_ingestion`'s `environment.variables` block:
```hcl
TICKERS = join(",", local.tracked_tickers)
```

(When the sentiment_analysis Lambda is created later in Week 3-4, give it the
same `TICKERS = join(",", local.tracked_tickers)` line.)

Run `terraform plan` then `terraform apply` (profile `terraform-user`, region
`us-east-1`) after this change to push the new env var to the deployed Lambda.

**`lambda/news_ingestion/handler.py`** — replace the hardcoded list:
```python
DEFAULT_TICKERS = [
    "NVDA", "LMT", "XOM", "AUR"
]
```
with a read from the same env var (keeping identical values as the local-dev
fallback, same pattern as `PG*` vars already work):
```python
import os

DEFAULT_TICKERS = os.environ.get("TICKERS", "NVDA,LMT,XOM,AUR").split(",")
```

**`.env` and `.env.example`** (both `lambda/news_ingestion/` and the new
`lambda/sentiment_analysis/` once it exists) — add:
```
TICKERS=NVDA,LMT,XOM,AUR
```
alongside the existing `FINNHUB_API_KEY`/`PG*` vars. Never put real secrets in
`.env.example` — this line is fine since it's not sensitive.

## Out of scope for this task (do not build yet)

This file only covers the schema + ticker centralization. Explicitly NOT part of
this task, per the incremental-scaffolding convention in CLAUDE.md — do these next,
as separate follow-ups, after this lands:
- Model selection / benchmarking candidates against an eval set
- Prompt design and the actual LangChain chain (`.with_structured_output(...)`)
- The deterministic aggregation step (per-article extractions → one row per
  ticker per day in `signals`)
- Hand-labeled eval set (~20-30 articles from the existing `articles` table)
- Deploying `sentiment_analysis` as its own Lambda / wiring it into Terraform
  beyond the `TICKERS` env var above

## Commands reference

- `uv add pydantic` if not already a dependency (check `pyproject.toml` first)
- `cd terraform && terraform plan` / `terraform apply` — after the lambda.tf edit
- No new dependency-group split needed yet for this task specifically, but note
  per CLAUDE.md: once LangChain itself is added as a dependency (the next task),
  that's the trigger to split `pyproject.toml`'s flat dependency list into groups,
  since sentiment_analysis's deps (langchain, a model SDK) differ from
  news_ingestion's (trafilatura, finnhub).
