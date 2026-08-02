from schema import TickerSentiment


def merge_article_ids(previous: dict | None, new_entries: list[tuple[int, TickerSentiment]]) -> list[int]:
    article_ids = list(previous["article_ids"]) if previous else []
    article_ids += [article_id for article_id, _ in new_entries]
    return article_ids


def average_involvement(previous: dict | None, new_entries: list[tuple[int, TickerSentiment]]) -> float:
    """Combined involvement stays a deterministic average - reconstructed from previous's
    stored mean + article count, same sufficient-statistics trick the old confidence-weighted
    combine used - rather than an LLM call, unlike sentiment/event_type (see combine_chain.py)."""
    n_prev = len(previous["article_ids"]) if previous else 0
    involvement_sum = (previous["involvement"] * n_prev) if previous else 0.0
    involvement_sum += sum(ts.involvement for _, ts in new_entries)
    return involvement_sum / (n_prev + len(new_entries))
