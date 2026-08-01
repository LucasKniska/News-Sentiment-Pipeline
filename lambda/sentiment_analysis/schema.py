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
    # wrong call can be inspected. Not part of the `signals` table - drop this field
    # once the chain's accuracy/confidence correlation checks out.
    reasoning: str = Field(description="One-sentence justification for the sentiment/event_type call")


class ArticleExtraction(BaseModel):
    ticker_sentiments: list[TickerSentiment] = Field(
        description="One entry per ticker with substantive discussion in the article. Skip tickers only mentioned in passing."
    )
