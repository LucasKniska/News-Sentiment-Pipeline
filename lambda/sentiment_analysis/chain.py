import json
import logging
import os
import re
import threading
import time
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

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", "Headline: {headline}\n\nArticle text:\n{text}"),
    ]
)

# Groq (free/cheap) default while iterating on the pipeline - swap back to an
# Anthropic model id (see run_eval.py) once the extraction is validated and the
# cost of running it for real is worth paying.
_DEFAULT_MODEL = "openai/gpt-oss-120b"


# Only two providers in use - anything not an Anthropic model id ("claude-...") is
# assumed Groq-hosted, rather than maintaining a name/prefix list that has to be
# kept in sync with GROQ_MODELS_BEST_TO_WORST below every time Groq's catalog changes.
# api_key overrides ChatGroq's own default env resolution (GROQ_API_KEY) - used by
# invoke_with_model_fallback to rotate across GROQ_API_KEYS, since each is a
# separate Groq account/org with its own independent daily token quota (TPD).
def get_llm(model: str = _DEFAULT_MODEL, api_key: str | None = None) -> BaseChatModel:
    if model.startswith("claude"):
        return ChatAnthropic(model=model, temperature=0)
    return ChatGroq(
        model=model, temperature=0, **({"groq_api_key": api_key} if api_key else {})
    )


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
# `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` were both dropped
# 2026-08-17 after `models.list()` showed Groq removed them from the catalog
# entirely (calls to either now 404 with "does not exist or you do not have
# access to it") - not a rename, no direct Llama replacement is currently
# active. Every call had been trying both dead rungs before falling through,
# which was pure wasted latency on every single extraction/combine call.
GROQ_MODELS_BEST_TO_WORST = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
]

# GROQ_API_KEY_2 is a second, separate Groq account - its own org, so its own
# independent per-model TPD pool (see the 2026-08-16 backfill incident: a single
# key/org meant one model's daily quota being tapped out blocked every call to that
# model regardless of how many other models still had headroom). Optional - falls
# back to a single-key list ([None], meaning "let ChatGroq resolve GROQ_API_KEY
# itself") when GROQ_API_KEY_2 isn't set, so this is a no-op until a second key is
# configured.
GROQ_API_KEYS: list[str | None] = [
    k for k in (os.environ.get("GROQ_API_KEY"), os.environ.get("GROQ_API_KEY_2")) if k
] or [None]

# Groq's 429s come in two flavors that behave very differently: TPD (tokens per
# day) won't clear for hours, while TPM (tokens per minute) clears in seconds.
# Treating them the same wastes calls - retrying a TPD-exhausted (model, key)
# combo for every subsequent article is a guaranteed-failing network round trip,
# while giving up on a TPM hit immediately abandons a model that's about to be
# usable again. Groq doesn't expose a structured Retry-After for this (the
# per-minute reset header exists, but there's no equivalent daily one), so both
# the flavor and the wait time are parsed out of the 429 message body itself.
_TPD_MARKER = "tokens per day (TPD)"
_RETRY_AFTER_RE = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)(ms|s)\b")


def _is_daily_rate_limit(error: Exception) -> bool:
    return _TPD_MARKER in str(error)


def _parse_retry_after(error: Exception, default: float = 1.0) -> float:
    match = _RETRY_AFTER_RE.search(str(error))
    if not match:
        return default
    hours, minutes, value, unit = match.groups()
    seconds = float(value) / 1000 if unit == "ms" else float(value)
    return seconds + int(minutes or 0) * 60 + int(hours or 0) * 3600


# (model, api_key) pairs already confirmed TPD-exhausted, shared across every
# extract_with_fallback/combine_signal call in this process - once a combo is known
# dead for the day, every subsequent article skips it outright instead of
# rediscovering the same 429 via a wasted network call. Reset only by a fresh
# process (new Lambda container / new local run), which is fine since Groq's TPD
# window is daily and every run here is bounded to at most one day anyway.
_exhausted_combos: set[tuple[str, str | None]] = set()
_exhausted_combos_lock = threading.Lock()

# One retry for a TPM hit (capped, since it's meant to clear in seconds - a raw
# Retry-After could in principle be long if many callers are contending for the
# same 8000 TPM pool at once, see the 2026-08-18 backfill investigation).
_TPM_MAX_RETRIES = 1
_TPM_RETRY_CAP_SECONDS = 15.0


def relevant_tickers(article: Article) -> list[str]:
    """Tickers this article is both linked to (articles.tickers) and tracked -
    the only ones we ever ask the model about. Shared by extract()/
    extract_with_fallback() below and by run.py, which needs the same set to
    know which tickers to mark as attempted after extraction."""
    return [t for t in article.tickers if t in TRACKED_TICKERS]


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
    tickers = relevant_tickers(article)
    if not tickers:
        return ArticleExtraction(ticker_sentiments=[])

    chain = chain or build_chain()
    return invoke_with_recovery(
        chain,
        {
            "tickers": ", ".join(tickers),
            "headline": article.headline,
            "text": article.text,
        },
        ArticleExtraction,
    )


def invoke_with_model_fallback(
    chain_builder: Callable[[BaseChatModel], Runnable],
    inputs: dict,
    output_model: type[BaseModel],
    models: list[str],
    api_keys: list[str | None] = GROQ_API_KEYS,
) -> tuple[BaseModel, str]:
    """Try each model in order (best first) until one produces a usable structured
    result, falling back on ANY failure - rate limits (a model's Groq quota is a
    separate pool per model, so this is often just "try the next one"), schema
    violations invoke_with_recovery couldn't fix, etc. Right now getting a usable
    structured output at all matters more than which specific model produced it.

    Within each model, also rotates across api_keys (separate Groq accounts, each
    with its own quota pool for that model) before dropping to the next, weaker
    model - a model's daily quota being tapped out on one key doesn't mean the same
    model is unusable, just that key is. Key-minor/model-major ordering so a busy
    day exhausts the best model's *combined* quota across both keys before ever
    falling back to a weaker model.

    A 429 gets special handling instead of falling straight through like any other
    failure (see _is_daily_rate_limit above): a TPD hit marks the (model, key) combo
    exhausted for the rest of this process, so no later article ever retries a
    combo already known dead; a TPM hit is retried in place (briefly) since it's
    expected to clear on its own within seconds."""
    last_error: Exception | None = None
    for model in models:
        for i, api_key in enumerate(api_keys):
            combo = (model, api_key)
            with _exhausted_combos_lock:
                if combo in _exhausted_combos:
                    continue

            retries_left = _TPM_MAX_RETRIES
            while True:
                try:
                    chain = chain_builder(get_llm(model, api_key))
                    return invoke_with_recovery(chain, inputs, output_model), model
                except groq.RateLimitError as e:
                    last_error = e
                    if _is_daily_rate_limit(e):
                        with _exhausted_combos_lock:
                            _exhausted_combos.add(combo)
                        logger.warning(
                            "Model %s (key #%d) hit its daily quota - skipping for the rest of this run: %s",
                            model,
                            i + 1,
                            e,
                        )
                        break
                    if retries_left > 0:
                        wait = min(_parse_retry_after(e), _TPM_RETRY_CAP_SECONDS)
                        logger.warning(
                            "Model %s (key #%d) hit a per-minute limit - retrying in %.1fs: %s",
                            model,
                            i + 1,
                            wait,
                            e,
                        )
                        time.sleep(wait)
                        retries_left -= 1
                        continue
                    logger.warning("Model %s (key #%d) failed: %s", model, i + 1, e)
                    break
                except Exception as e:
                    logger.warning("Model %s (key #%d) failed: %s", model, i + 1, e)
                    last_error = e
                    break
    # last_error is still None if every (model, key) combo was already in
    # _exhausted_combos before this call even tried one - i.e. every option is
    # known TPD-dead for the day, not just this article's.
    raise last_error or RuntimeError(
        "All models/keys already marked daily-quota-exhausted for this run"
    )


def extract_with_fallback(
    article: Article,
    models: list[str] = GROQ_MODELS_BEST_TO_WORST,
) -> tuple[ArticleExtraction, str | None]:
    """Same ticker-filtering as extract(), but tries GROQ_MODELS_BEST_TO_WORST in
    order instead of a single fixed model. Returns (result, model_that_succeeded) -
    the model name is None only for the no-LLM-call empty-result short-circuit."""
    tickers = relevant_tickers(article)
    if not tickers:
        return ArticleExtraction(ticker_sentiments=[]), None

    inputs = {
        "tickers": ", ".join(tickers),
        "headline": article.headline,
        "text": article.text,
    }
    return invoke_with_model_fallback(build_chain, inputs, ArticleExtraction, models)
