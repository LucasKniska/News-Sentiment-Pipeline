import argparse
import csv
import json
import re
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character article text may contain (e.g. currency symbols).
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

import groq  # noqa: E402  (must import after load_dotenv, see local_run.py)
from chain import _PROMPT, get_llm  # noqa: E402
from langchain_anthropic import ChatAnthropic  # noqa: E402
from run_eval import (  # noqa: E402
    _EVAL_TICKER,
    _SKIP_INVOLVEMENT_THRESHOLD,
    _load_rows,
    _to_article,
)
from schema import ArticleExtraction  # noqa: E402

# $/1M tokens (input, output). Verified live against Groq's and Anthropic's own
# pricing docs on 2026-08-21 - not guessed. Groq's catalog has changed under this
# project before (see chain.py's GROQ_MODELS_BEST_TO_WORST comment), so re-check
# console.groq.com/docs/pricing if a model id here ever 404s. Claude Sonnet 5's
# $2/$10 rate is Anthropic's confirmed *standard* price (a previously-scheduled
# increase to $3/$15 on 2026-09-01 was cancelled), not an expiring intro rate.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "qwen/qwen3.6-27b": (0.60, 3.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
}
DEFAULT_MODELS = list(MODEL_PRICING)

_FAILED_GENERATION_RE = re.compile(r"<function=\w+>(.*)</function>", re.DOTALL)


def _get_llm(model: str):
    """chain.py's get_llm() hardcodes temperature=0 for every Anthropic model, which
    claude-haiku-4-5 accepts but claude-sonnet-5 rejects outright (400: "temperature
    is deprecated for this model") - discovered running this script, since get_llm's
    claude branch was previously dormant in production (the deployed ladder is
    Groq-only). Not fixed in chain.py itself (out of scope here, and harmless today
    since nothing there points at claude-sonnet-5 yet) - just bypassed locally for
    Anthropic models so this comparison isn't blocked by it."""
    if model.startswith("claude"):
        return ChatAnthropic(model=model)
    return get_llm(model)


def _percentile(data: list[float], pct: float) -> float:
    """Linear-interpolation percentile - statistics.quantiles' bucket-based
    approach gets coarse at the eval set's small n, this stays well-defined
    down to n=1."""
    if not data:
        return float("nan")
    data = sorted(data)
    k = (len(data) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(data) - 1)
    if f == c:
        return data[f]
    return data[f] + (data[c] - data[f]) * (k - f)


def _invoke_one(chain, inputs: dict) -> tuple[ArticleExtraction | None, dict | None, str | None]:
    """Returns (parsed_result, usage_metadata, error). Mirrors chain.py's
    invoke_with_recovery, but adapted for with_structured_output(include_raw=True)'s
    {"raw", "parsed", "parsing_error"} dict shape, which invoke_with_recovery doesn't
    handle - and reimplemented locally rather than changing chain.py itself, since
    that file backs the deployed, scheduled sentiment_analysis Lambda."""
    try:
        result = chain.invoke(inputs)
    except groq.BadRequestError as e:
        # Groq's tool-calling API hard-rejects a schema-mismatched response with a
        # 400 before we ever see a raw AIMessage, so there's no usage_metadata to
        # recover here even when the generation itself is salvageable.
        body = e.body if isinstance(e.body, dict) else {}
        failed_generation = body.get("error", {}).get("failed_generation") or ""
        match = _FAILED_GENERATION_RE.search(failed_generation)
        if not match:
            return None, None, str(e)
        try:
            return ArticleExtraction.model_validate(json.loads(match.group(1))), None, None
        except Exception:
            return None, None, str(e)
    except Exception as e:
        return None, None, str(e)

    if result["parsing_error"] is not None:
        return None, None, str(result["parsing_error"])
    raw = result["raw"]
    usage = getattr(raw, "usage_metadata", None)
    return result["parsed"], usage, None


def run_model(model: str, rows: list[dict]) -> tuple[dict, list[dict]]:
    chain = _PROMPT | _get_llm(model).with_structured_output(
        ArticleExtraction, include_raw=True
    )

    abs_errors, latencies = [], []
    omitted_on_rated = skip_agreements = skip_total = fail_count = 0
    in_tokens_total = out_tokens_total = 0
    raw_records = []

    for i, row in enumerate(rows, 1):
        article = _to_article(row)
        inputs = {
            "tickers": _EVAL_TICKER,
            "headline": article.headline,
            "text": article.text,
        }
        start = time.perf_counter()
        parsed, usage, error = _invoke_one(chain, inputs)
        latency = time.perf_counter() - start

        record = {
            "model": model,
            "article_id": row["id"],
            "human_sentiment": row["human_sentiment"].strip(),
            "predicted_sentiment": "",
            "involvement": "",
            "entry_present": False,
            "latency_s": round(latency, 3),
            "input_tokens": "",
            "output_tokens": "",
            "error": error or "",
        }

        if error is not None:
            fail_count += 1
            raw_records.append(record)
            print(f"  [{i}/{len(rows)}] {model} article {row['id']}: FAILED - {error}")
            continue

        latencies.append(latency)
        if usage:
            record["input_tokens"] = usage.get("input_tokens", "")
            record["output_tokens"] = usage.get("output_tokens", "")
            in_tokens_total += usage.get("input_tokens", 0) or 0
            out_tokens_total += usage.get("output_tokens", 0) or 0

        entry = next(
            (ts for ts in parsed.ticker_sentiments if ts.ticker == _EVAL_TICKER), None
        )
        if entry is not None:
            record["predicted_sentiment"] = entry.sentiment
            record["involvement"] = entry.involvement
            record["entry_present"] = True

        human = record["human_sentiment"]
        if human == "skip":
            skip_total += 1
            if entry is None or entry.involvement < _SKIP_INVOLVEMENT_THRESHOLD:
                skip_agreements += 1
        else:
            target = float(human)
            if entry is None:
                omitted_on_rated += 1
            else:
                abs_errors.append(abs(entry.sentiment - target))

        raw_records.append(record)
        print(f"  [{i}/{len(rows)}] {model} article {row['id']}: ok ({latency:.2f}s)")

    input_price, output_price = MODEL_PRICING.get(model, (None, None))
    cost = (
        (in_tokens_total / 1_000_000) * input_price
        + (out_tokens_total / 1_000_000) * output_price
        if input_price is not None
        else None
    )

    summary = {
        "model": model,
        "n": len(rows),
        "mae": statistics.mean(abs_errors) if abs_errors else None,
        "omitted": omitted_on_rated,
        "skip_agreement": f"{skip_agreements}/{skip_total}" if skip_total else "n/a",
        "fail_count": fail_count,
        "fail_rate": fail_count / len(rows) if rows else 0.0,
        "latency_mean_s": statistics.mean(latencies) if latencies else None,
        "latency_p50_s": _percentile(latencies, 0.50) if latencies else None,
        "latency_p95_s": _percentile(latencies, 0.95) if latencies else None,
        "input_tokens_total": in_tokens_total,
        "output_tokens_total": out_tokens_total,
        "input_price_per_1m": input_price,
        "output_price_per_1m": output_price,
        "est_cost_usd": cost,
    }
    return summary, raw_records


def _print_summary_table(summaries: list[dict]) -> None:
    header = (
        f"\n{'model':<24}{'n':<4}{'MAE':<8}{'omit':<6}{'skip':<8}{'fail':<8}"
        f"{'lat mean':<10}{'lat p50':<10}{'lat p95':<10}{'in tok':<9}{'out tok':<9}{'est $':<8}"
    )
    print(header)
    for s in summaries:
        mae = f"{s['mae']:.3f}" if s["mae"] is not None else "n/a"
        lat_mean = f"{s['latency_mean_s']:.2f}" if s["latency_mean_s"] is not None else "n/a"
        lat_p50 = f"{s['latency_p50_s']:.2f}" if s["latency_p50_s"] is not None else "n/a"
        lat_p95 = f"{s['latency_p95_s']:.2f}" if s["latency_p95_s"] is not None else "n/a"
        cost = f"{s['est_cost_usd']:.4f}" if s["est_cost_usd"] is not None else "n/a"
        print(
            f"{s['model']:<24}{s['n']:<4}{mae:<8}{s['omitted']:<6}{s['skip_agreement']:<8}"
            f"{s['fail_count']:<8}{lat_mean:<10}{lat_p50:<10}{lat_p95:<10}"
            f"{s['input_tokens_total']:<9}{s['output_tokens_total']:<9}{cost:<8}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the hand-rated eval set through each candidate model "
        "individually (no ladder fallback), reporting per-model accuracy, "
        "latency, token usage, and estimated $ cost."
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=DEFAULT_MODELS,
        help=f"Model ids to compare (default: {', '.join(DEFAULT_MODELS)}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only run the first N eval rows (deterministic order). Default: all rows.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).parent / "eval",
        help="Directory to write model_comparison_summary.csv / _raw.csv into.",
    )
    args = parser.parse_args()

    rows = _load_rows()
    if args.limit:
        rows = rows[: args.limit]
    print(f"Running {len(args.models)} model(s) over {len(rows)} rated articles each...")

    summaries, all_raw_records = [], []
    for model in args.models:
        print(f"\n=== {model} ===")
        summary, raw_records = run_model(model, rows)
        summaries.append(summary)
        all_raw_records.extend(raw_records)

    _print_summary_table(summaries)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.out_dir / "model_comparison_summary.csv"
    raw_path = args.out_dir / "model_comparison_raw.csv"

    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0].keys()))
        writer.writeheader()
        writer.writerows(summaries)

    with open(raw_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_raw_records[0].keys()))
        writer.writeheader()
        writer.writerows(all_raw_records)

    print(f"\nWrote {summary_path}")
    print(f"Wrote {raw_path}")


if __name__ == "__main__":
    main()
