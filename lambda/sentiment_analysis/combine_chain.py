from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from aggregate import average_involvement, merge_article_ids
from chain import get_llm, invoke_with_recovery
from schema import CombinedSignal, TickerSentiment

COMBINE_SYSTEM_PROMPT = """You are combining today's sentiment signal for a single \
tracked ticker from multiple sources into one blended daily view.

You will be given:
- The ticker's cumulative signal from earlier runs today, if any: its blended \
sentiment and involvement so far, and how many articles already contributed.
- A list of newly-extracted per-article signals for this ticker from articles \
published today that haven't been factored in yet. Each has its own sentiment \
(-1 to 1), event_type, involvement (0 = tangential/background mention, 1 = the \
article is primarily about this ticker), and reasoning.

Produce ONE blended sentiment (-1 to 1) and ONE event_type for this ticker's day \
so far, combining the previous cumulative signal (if any) with the new articles.

Weight each input by its involvement when deciding the blended sentiment: an \
input with low involvement should move the blended sentiment much less than one \
with high involvement. Treat the previous cumulative signal as itself carrying \
the combined weight of every article that already contributed to it (its \
involvement times the number of prior articles) - do not let one new \
low-involvement article outweigh an established high-involvement trend, and do \
not let a single new high-involvement article get diluted away just because the \
prior signal was based on many low-involvement articles.

For event_type, pick the single event category that best characterizes the most \
significant news driving today's signal for this ticker - usually the \
highest-involvement contributor, not necessarily the most recent one."""

_COMBINE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", COMBINE_SYSTEM_PROMPT),
    ("human", "Ticker: {ticker}\n\nPrevious cumulative signal:\n{previous_summary}\n\nNew article signals:\n{new_entries_summary}"),
])


def build_combine_chain(llm=None) -> Runnable:
    llm = llm or get_llm()
    return _COMBINE_PROMPT | llm.with_structured_output(CombinedSignal)


def _format_previous(previous: dict | None) -> str:
    if not previous:
        return "None - this is the first signal for this ticker today."
    n = len(previous["article_ids"])
    return f"sentiment={previous['sentiment']:.2f}, involvement={previous['involvement']:.2f}, based on {n} article(s) so far"


def _format_new_entries(new_entries: list[tuple[int, TickerSentiment]]) -> str:
    lines = [
        f"- sentiment={ts.sentiment:.2f}, event_type={ts.event_type.value}, "
        f"involvement={ts.involvement:.2f}, reasoning: {ts.reasoning}"
        for _, ts in new_entries
    ]
    return "\n".join(lines)


def combine_signal(
    previous: dict | None,
    new_entries: list[tuple[int, TickerSentiment]],
    ticker: str,
    chain: Runnable | None = None,
) -> dict:
    chain = chain or build_combine_chain()
    result: CombinedSignal = invoke_with_recovery(chain, {
        "ticker": ticker,
        "previous_summary": _format_previous(previous),
        "new_entries_summary": _format_new_entries(new_entries),
    }, CombinedSignal)
    return {
        "sentiment": result.sentiment,
        "event_type": result.event_type.value,
        "involvement": average_involvement(previous, new_entries),
        "article_ids": merge_article_ids(previous, new_entries),
    }
