import sys

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

from chain import GROQ_MODELS_BEST_TO_WORST, invoke_with_model_fallback  # noqa: E402
from schema import ArticleExtraction, EventType, TickerSentiment  # noqa: E402

# How many "successful" calls a model gets before it starts failing every
# subsequent call - simulates a model's Groq quota running out mid-run.
_CALLS_BEFORE_EXHAUSTION = 5

_DUMMY_RESULT = ArticleExtraction(
    ticker_sentiments=[
        TickerSentiment(
            ticker="AAPL",
            sentiment=0.0,
            event_type=EventType.market_wide_movement,
            involvement=0.1,
            reasoning="stub",
        )
    ]
)


class _FakeChain:
    """Stands in for build_chain(llm)'s real Runnable inside invoke_with_model_fallback.
    Real get_llm() still constructs the actual ChatGroq client for each model (see
    fake_chain_builder below) - this only fakes the network call itself, so the
    orchestration logic under test (invoke_with_model_fallback) is the real thing."""

    def __init__(self, model: str, call_counts: dict[str, int]):
        self.model = model
        self.call_counts = call_counts

    def invoke(self, inputs: dict) -> ArticleExtraction:
        count = self.call_counts.get(self.model, 0) + 1
        self.call_counts[self.model] = count
        if count > _CALLS_BEFORE_EXHAUSTION:
            raise RuntimeError(f"simulated exhaustion for {self.model} (call {count})")
        return _DUMMY_RESULT


def main() -> None:
    call_counts: dict[str, int] = {}

    def fake_chain_builder(llm) -> _FakeChain:
        return _FakeChain(llm.model_name, call_counts)

    n_calls = _CALLS_BEFORE_EXHAUSTION * len(GROQ_MODELS_BEST_TO_WORST)
    models_used = []
    for i in range(n_calls):
        _, model_used = invoke_with_model_fallback(
            fake_chain_builder,
            {"tickers": "AAPL", "headline": "x", "text": "y"},
            ArticleExtraction,
            GROQ_MODELS_BEST_TO_WORST,
        )
        models_used.append(model_used)
        print(f"call {i + 1:>2}: handled by {model_used}")

    expected = [
        model
        for model in GROQ_MODELS_BEST_TO_WORST
        for _ in range(_CALLS_BEFORE_EXHAUSTION)
    ]
    assert (
        models_used == expected
    ), f"rotation mismatch:\n  expected {expected}\n  got      {models_used}"
    print("\nOK - rotation matched the expected best-to-worst schedule exactly.")


if __name__ == "__main__":
    main()
