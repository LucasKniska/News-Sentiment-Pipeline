from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_groq import ChatGroq

from models import Article
from schema import TRACKED_TICKERS, ArticleExtraction

SYSTEM_PROMPT = """You are a financial news analyst extracting structured sentiment \
signals from a news article for a small set of tracked companies.

Tracked tickers: {tickers}

For each tracked ticker that appears anywhere in the article - even only as \
market context rather than the article's main subject - extract:
- sentiment: how positive or negative the article's discussion of THIS ticker \
specifically is, from -1 (very negative) to 1 (very positive). Different tickers \
in the same article can and should get different scores if the article discusses \
them differently - do not blend them into one overall tone.
- event_type: the single business/operational event category that best describes \
what's being reported about this ticker.
- involvement: how central this ticker's discussion is to the article, from 0 \
(tangential or background mention - e.g. a broad market-wide piece, or an article \
centered on a different company that happens to name this ticker in passing; still \
score its sentiment/event_type, just with low involvement) to 1 (the article is \
primarily about this ticker). This is not a confidence score - it measures how \
much of the article is about this ticker, not how sure you are of the call.
- reasoning: one sentence justifying the call.

Only omit a tracked ticker entirely if the article's scraped text is not real \
content - e.g. a paywall notice ("Upgrade to read..."), a JS-blocked error page \
("Please enable JavaScript..."), or a bare teaser with no actual reporting - even \
if the ticker's name or symbol appears in that boilerplate. If the article has no \
usable content at all, return an empty list."""

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Headline: {headline}\n\nArticle text:\n{text}"),
])

# Cheap/fast default - swap the model id to benchmark against the eval set later;
# nothing else in this module needs to change to compare candidates.
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Model ids with these prefixes are Groq-hosted (open-weight) rather than Anthropic -
# see eval/run_eval.py, which benchmarks a Groq model as a cheaper/faster alternative
# to the Anthropic default.
_GROQ_MODEL_PREFIXES = ("llama", "kimi", "gemma", "mixtral", "deepseek", "qwen")


def get_llm(model: str = _DEFAULT_MODEL) -> BaseChatModel:
    if model.startswith(_GROQ_MODEL_PREFIXES):
        return ChatGroq(model=model, temperature=1)
    return ChatAnthropic(model=model, temperature=1)


def build_chain(llm: BaseChatModel | None = None) -> Runnable:
    llm = llm or get_llm()
    return _PROMPT | llm.with_structured_output(ArticleExtraction)


def extract(article: Article, chain: Runnable | None = None) -> ArticleExtraction:
    chain = chain or build_chain()
    return chain.invoke({
        "tickers": ", ".join(TRACKED_TICKERS),
        "headline": article.headline,
        "text": article.text,
    })
