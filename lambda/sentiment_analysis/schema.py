import os
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# Sourced from the TICKERS env var (see section 2) so this project's scope stays
# in sync with lambda/news_ingestion/handler.py's ticker list — no duplication.
TRACKED_TICKERS = tuple(os.environ.get("TICKERS", "NVDA,LMT,XOM,AUR,AAPL").split(","))
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
    # Catch-all for a broad market/sector-wide move (e.g. an AI-stock selloff, a
    # rate-driven rally) that touches this ticker through shared exposure rather
    # than a distinct event specific to it - use only when none of the above fits.
    market_wide_movement = "market_wide_movement"
    # A specific competitor's move (product, pricing, market share) pressuring this
    # ticker - named to match the other event-not-outcome categories rather than
    # the more generic "competition".
    competitive_pressure = "competitive_pressure"


class TickerSentiment(BaseModel):
    ticker: Ticker = Field(description="Ticker this sentiment applies to - must be one of the tickers listed in the prompt")
    sentiment: float = Field(ge=-1, le=1, description="Sentiment of the article's discussion of this specific ticker, -1 to 1")
    event_type: EventType
    involvement: float = Field(
        ge=0,
        le=1,
        description="How central/substantive this ticker's discussion is in the article, 0 to 1. "
        "0 = tangential - e.g. a broad market-wide piece, or an article centered on a different company "
        "that this ticker merely shares market/sector exposure with. 1 = the article is primarily about "
        "this ticker. This is not a confidence/certainty score - it measures how much of the article "
        "concerns this ticker, not how sure you are of the call. Never a reason to omit the ticker.",
    )
    # TODO(cut-before-ship): kept only while calibrating against the eval set so a
    # wrong call can be inspected. Not part of the `signals` table - drop this field
    # once the chain's accuracy/involvement correlation checks out.
    reasoning: str = Field(description="One-sentence justification for the sentiment/event_type call")


class ArticleExtraction(BaseModel):
    ticker_sentiments: list[TickerSentiment] = Field(
        description="Exactly one entry per ticker listed in the prompt - never fewer, and never an "
        "entry for a ticker not listed there (chain.py's extract() has already filtered the list down "
        "to tickers confirmed relevant to this article). The only exception: return an empty list if "
        "the article's scraped text itself is not real content (e.g. a paywall notice, a JS-blocked "
        "error page, or a bare teaser with no actual reporting)."
    )


class CombinedSignal(BaseModel):
    """Output of the second (combine) chain - blends this ticker's previous cumulative
    signal with today's newly-extracted per-article TickerSentiments into one value."""

    sentiment: float = Field(ge=-1, le=1, description="Blended sentiment for this ticker's day so far, -1 to 1")
    event_type: EventType
    # TODO(cut-before-ship): kept only while calibrating against the eval set so a
    # wrong combine call can be inspected. Not part of the `signals` table.
    reasoning: str | None = Field(default=None, description="One-sentence justification for the blended sentiment/event_type call")
