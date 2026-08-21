import csv
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character article text may contain (e.g. currency symbols).
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from chain import (
    extract_with_fallback,
)  # noqa: E402  (must import after load_dotenv, see local_run.py)
from models import Article  # noqa: E402

# The ticker build_eval_set.py sampled and eval_set.csv was hand-rated against -
# not necessarily in TRACKED_TICKERS today, but must be for extract() to accept it
# (schema.py's Ticker literal validates against TRACKED_TICKERS).
_EVAL_TICKER = "AAPL"
_EVAL_SET_PATH = Path(__file__).parent / "eval" / "eval_set.csv"

# Below this involvement, "mentioned AAPL but barely" counts as agreeing with a
# human "skip" rating rather than as a false positive.
_SKIP_INVOLVEMENT_THRESHOLD = 0.3


def _load_rows() -> list[dict]:
    with open(_EVAL_SET_PATH, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["human_sentiment"].strip()]
    if not rows:
        raise SystemExit(
            f"No rated rows in {_EVAL_SET_PATH} - run build_eval_set.py and hand-rate it first."
        )
    return rows


def _to_article(row: dict) -> Article:
    return Article(
        id=int(row["id"]),
        headline=row["headline"],
        text=row["text"],
        url=row["url"] or None,
        datetime=datetime.fromisoformat(row["datetime"]),
        tickers=[_EVAL_TICKER],
        ingested_at=datetime.fromisoformat(row["datetime"]),
    )


def run_eval(rows: list[dict]) -> dict:
    """Runs each article through extract_with_fallback (chain.py's best-to-worst
    Groq model ladder) rather than a single fixed model - right now the open
    question is whether the schema/prompt produces a usable result at all, not
    which specific model produced it, so this tracks which rung of the ladder
    each article actually needed alongside the usual accuracy numbers."""
    model_successes: Counter[str] = Counter()
    abs_errors = []
    omitted_on_rated = 0
    skip_agreements = 0
    skip_total = 0
    all_models_failed = 0

    start = time.perf_counter()
    for row in rows:
        article = _to_article(row)
        try:
            result, model_used = extract_with_fallback(article)
        except Exception as e:
            print(f"  all models failed for article {row['id']}: {e}")
            all_models_failed += 1
            continue
        if model_used:
            model_successes[model_used] += 1

        entry = next(
            (ts for ts in result.ticker_sentiments if ts.ticker == _EVAL_TICKER), None
        )
        human = row["human_sentiment"].strip()

        if human == "skip":
            skip_total += 1
            if entry is None or entry.involvement < _SKIP_INVOLVEMENT_THRESHOLD:
                skip_agreements += 1
            continue

        target = float(human)
        if entry is None:
            omitted_on_rated += 1
            continue
        abs_errors.append(abs(entry.sentiment - target))
    elapsed = time.perf_counter() - start

    return {
        "n_rated": len(abs_errors),
        "mae": statistics.mean(abs_errors) if abs_errors else None,
        "omitted_on_rated": omitted_on_rated,
        "skip_agreement": f"{skip_agreements}/{skip_total}" if skip_total else "n/a",
        "all_models_failed": all_models_failed,
        "seconds": elapsed,
        "model_successes": model_successes,
    }


def main() -> None:
    rows = _load_rows()
    print(f"Running fallback pipeline over {len(rows)} rated articles...")
    result = run_eval(rows)

    print(
        f"\n{'MAE':<8}{'n':<5}{'omitted':<10}{'skip agree':<12}{'all-failed':<12}{'seconds':<8}"
    )
    mae = f"{result['mae']:.3f}" if result["mae"] is not None else "n/a"
    print(
        f"{mae:<8}{result['n_rated']:<5}{result['omitted_on_rated']:<10}{result['skip_agreement']:<12}{result['all_models_failed']:<12}{result['seconds']:<8.1f}"
    )

    print("\nWhich model handled each article (best rung first):")
    for model, count in result["model_successes"].most_common():
        print(f"  {model:<28}{count}")


if __name__ == "__main__":
    main()
