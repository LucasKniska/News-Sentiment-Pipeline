import json
import logging
import re
from typing import Callable

import groq
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_groq import ChatGroq
from pydantic import BaseModel

from models import Article
from schema import TRACKED_TICKERS, ArticleExtraction

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a financial news analyst extracting structured sentiment \
signals from a news article, for a specific set of tickers already confirmed to be \
connected to this article.

Tickers to analyze: {tickers}

Produce exactly one entry per ticker listed above - never fewer, and never an entry \
for any other ticker. The only exception: if the article's scraped text is not real \
content - e.g. a paywall notice ("Upgrade to read..."), a JS-blocked error page \
("Please enable JavaScript..."), or a bare teaser with no actual reporting - return \
an empty list instead, regardless of which tickers were listed above.

For each listed ticker, extract:
- sentiment: how positive or negative the article's discussion of THIS ticker \
specifically is, from -1 (very negative) to 1 (very positive). Different tickers \
in the same article can and should get different scores if the article discusses \
them differently - do not blend them into one overall tone.
- event_type: the single business/operational event category that best describes \
what's being reported that's relevant to this ticker. If the article ties to this \
ticker through a distinct event with its own category below (e.g. an export ban, a \
supply chain issue specific to it), use that category even if the framing is \
market-wide. Only use market_wide_movement when the connection is purely a broad \
market/sector move (e.g. a general AI-stock selloff, a rate-driven rally) with no \
distinct event of its own driving it.
- involvement: how central this ticker's discussion is to the article, from 0 \
(tangential - e.g. a broad market-wide piece, or an article centered on a different \
company that this ticker merely shares market/sector exposure with - a story about \
Microsoft's AI spending is still relevant to Apple as another large AI-exposed tech \
stock, so score it, just with low involvement) to 1 (the article is primarily about \
this ticker). This is not a confidence score - it measures how much of the article \
concerns this ticker, not how sure you are of the call.
- reasoning: one sentence justifying the call.

Every ticker listed above was already confirmed to be connected to this article \
before you saw it, so there is no such thing as a listed ticker with no real \
connection - always make a genuine best-effort call grounded in the article's \
content (using overall market/sector context where the connection is indirect) \
rather than inventing a placeholder or no-op entry."""

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Headline: {headline}\n\nArticle text:\n{text}"),
])

# Groq (free/cheap) default while iterating on the pipeline - swap back to an
# Anthropic model id (see run_eval.py) once the extraction is validated and the
# cost of running it for real is worth paying.
_DEFAULT_MODEL = "llama-3.3-70b-versatile"

# Only two providers in use - anything not an Anthropic model id ("claude-...") is
# assumed Groq-hosted, rather than maintaining a name/prefix list that has to be
# kept in sync with GROQ_MODELS_BEST_TO_WORST below every time Groq's catalog changes.
def get_llm(model: str = _DEFAULT_MODEL) -> BaseChatModel:
    if model.startswith("claude"):
        return ChatAnthropic(model=model, temperature=0)
    return ChatGroq(model=model, temperature=0)


# Groq's currently-active general-purpose chat models (verified via
# groq.Groq().models.list(), not guessed - Groq's catalog also includes non-chat
# models this list deliberately excludes: whisper-* (speech-to-text),
# canopylabs/orpheus-* (text-to-speech), meta-llama/llama-prompt-guard-2-*
# (injection-detection classifiers, not general chat), allam-2-7b (Arabic-focused,
# 4k context), openai/gpt-oss-safeguard-20b (safety-classification-tuned, not
# general-purpose), and groq/compound[-mini] (Groq's own agentic wrapper systems
# with their own built-in tool use, which fights with our structured-output tool
# schema). Ranked best-to-worst by rough capability tier (mostly parameter count) -
# Groq doesn't publish a benchmarked ranking, so this is a best-effort ordering.
GROQ_MODELS_BEST_TO_WORST = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
]


def build_chain(llm: BaseChatModel | None = None) -> Runnable:
    llm = llm or get_llm()
    return _PROMPT | llm.with_structured_output(ArticleExtraction)


_FAILED_GENERATION_RE = re.compile(r"<function=\w+>(.*)</function>", re.DOTALL)


def invoke_with_recovery(chain: Runnable, inputs: dict, output_model: type[BaseModel]):
    """Groq's tool-calling API (langchain_groq's default with_structured_output
    method) validates the model's tool call server-side and hard-rejects the whole
    response with a 400 on any schema mismatch, rather than handing us the raw JSON
    to fix up ourselves - even when the only problem is a stray type mismatch (e.g.
    "0.1" instead of 0.1) that Pydantic's own (non-strict) validation would coerce
    without complaint. The rejected response's raw tool call is still echoed back in
    the error body, so re-parse and re-validate that ourselves before giving up."""
    try:
        return chain.invoke(inputs)
    except groq.BadRequestError as e:
        body = e.body if isinstance(e.body, dict) else {}
        failed_generation = body.get("error", {}).get("failed_generation") or ""
        match = _FAILED_GENERATION_RE.search(failed_generation)
        if not match:
            raise
        try:
            return output_model.model_validate(json.loads(match.group(1)))
        except Exception:
            raise e from None


def extract(article: Article, chain: Runnable | None = None) -> ArticleExtraction:
    # Only ask about tickers this article is already connected to (articles.tickers -
    # see handler.py's merge-on-conflict logic) rather than every TRACKED_TICKERS
    # entry - this is what lets the prompt forbid placeholder/omitted entries above,
    # and it saves a call entirely when nothing tracked applies.
    relevant_tickers = [t for t in article.tickers if t in TRACKED_TICKERS]
    if not relevant_tickers:
        return ArticleExtraction(ticker_sentiments=[])

    chain = chain or build_chain()
    return invoke_with_recovery(chain, {
        "tickers": ", ".join(relevant_tickers),
        "headline": article.headline,
        "text": article.text,
    }, ArticleExtraction)


def invoke_with_model_fallback(
    chain_builder: Callable[[BaseChatModel], Runnable],
    inputs: dict,
    output_model: type[BaseModel],
    models: list[str],
) -> tuple[BaseModel, str]:
    """Try each model in order (best first) until one produces a usable structured
    result, falling back on ANY failure - rate limits (a model's Groq quota is a
    separate pool per model, so this is often just "try the next one"), schema
    violations invoke_with_recovery couldn't fix, etc. Right now getting a usable
    structured output at all matters more than which specific model produced it."""
    last_error: Exception | None = None
    for model in models:
        try:
            chain = chain_builder(get_llm(model))
            return invoke_with_recovery(chain, inputs, output_model), model
        except Exception as e:
            logger.warning("Model %s failed: %s", model, e)
            last_error = e
    raise last_error


def extract_with_fallback(
    article: Article,
    models: list[str] = GROQ_MODELS_BEST_TO_WORST,
) -> tuple[ArticleExtraction, str | None]:
    """Same ticker-filtering as extract(), but tries GROQ_MODELS_BEST_TO_WORST in
    order instead of a single fixed model. Returns (result, model_that_succeeded) -
    the model name is None only for the no-LLM-call empty-result short-circuit."""
    relevant_tickers = [t for t in article.tickers if t in TRACKED_TICKERS]
    if not relevant_tickers:
        return ArticleExtraction(ticker_sentiments=[]), None

    inputs = {
        "tickers": ", ".join(relevant_tickers),
        "headline": article.headline,
        "text": article.text,
    }
    return invoke_with_model_fallback(build_chain, inputs, ArticleExtraction, models)
