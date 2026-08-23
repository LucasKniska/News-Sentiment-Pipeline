import argparse
import csv
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character article text may contain (e.g. currency symbols).
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from db import get_connection  # noqa: E402  (must import after load_dotenv, see local_run.py)

# Lower and unweighted vs. price_correlation.py's 0.3/involvement-weighted floor -
# deliberate, so source A is a genuinely different aggregation to compare against
# source B (the already-combined signals table) rather than a re-run of the same
# numbers.
_INVOLVEMENT_FLOOR = 0.2

# Full decision-boundary sweep, not a confidence filter like price_correlation.py's
# abs(sentiment) >= t. Every row participates at every threshold here - see
# _accuracy().
_THRESHOLDS = [round(-0.75 + 0.05 * i, 2) for i in range(31)]

_SPLIT_FRACTION = 0.8

# Below this, an accuracy number is mostly noise - print a warning instead of a
# figure that looks precise but isn't (signals is a much smaller table than
# article_sentiment, see CLAUDE.md).
_MIN_SPLIT_N = 20

_SOURCES = ("article_sentiment", "signals")
_HORIZONS = (0, 1)

# Source A: per ticker/day, the simple (unweighted) mean of article_sentiment.sentiment
# for rows with involvement >= _INVOLVEMENT_FLOOR. LAG/LEAD give same-day and
# forward-day close baselines in one pass, same as price_correlation.py.
_ARTICLE_SENTIMENT_QUERY = """
    WITH daily_sentiment AS (
        SELECT
            s.ticker,
            a.datetime::date AS date,
            AVG(s.sentiment) AS sentiment,
            COUNT(*) AS n_articles
        FROM article_sentiment s
        JOIN articles a ON a.id = s.article_id
        WHERE s.involvement >= %(involvement_floor)s
        GROUP BY s.ticker, a.datetime::date
    ),
    price_moves AS (
        SELECT
            ticker,
            date,
            close,
            LAG(close) OVER (PARTITION BY ticker ORDER BY date) AS prev_close,
            LEAD(close) OVER (PARTITION BY ticker ORDER BY date) AS next_close
        FROM daily_prices
    )
    SELECT ds.ticker, ds.date, ds.sentiment, pm.prev_close, pm.close, pm.next_close
    FROM daily_sentiment ds
    JOIN price_moves pm ON pm.ticker = ds.ticker AND pm.date = ds.date
    ORDER BY ds.ticker, ds.date
"""

# Source B: per ticker/day, the latest signals.sentiment value. A signal's date is
# derived from its article_ids rather than trusting timestamp::date - db.py's
# _SELECT_LATEST_SIGNAL_SQL comment warns timestamp is when the combine run
# executed, not the articles' publish date (backfill runs process arbitrary
# historical dates), so grouping by timestamp::date would misattribute rows to
# the wrong trading day.
_SIGNALS_QUERY = """
    WITH signal_days AS (
        SELECT DISTINCT s.id, s.ticker, s.sentiment, s.timestamp, a.datetime::date AS date
        FROM signals s
        JOIN articles a ON a.id = ANY(s.article_ids)
    ),
    daily_signal AS (
        SELECT DISTINCT ON (ticker, date) ticker, date, sentiment
        FROM signal_days
        ORDER BY ticker, date, timestamp DESC
    ),
    price_moves AS (
        SELECT
            ticker,
            date,
            close,
            LAG(close) OVER (PARTITION BY ticker ORDER BY date) AS prev_close,
            LEAD(close) OVER (PARTITION BY ticker ORDER BY date) AS next_close
        FROM daily_prices
    )
    SELECT ds.ticker, ds.date, ds.sentiment, pm.prev_close, pm.close, pm.next_close
    FROM daily_signal ds
    JOIN price_moves pm ON pm.ticker = ds.ticker AND pm.date = ds.date
    ORDER BY ds.ticker, ds.date
"""


def _fetch_raw(source: str) -> list[dict]:
    query = _ARTICLE_SENTIMENT_QUERY if source == "article_sentiment" else _SIGNALS_QUERY
    params = {"involvement_floor": _INVOLVEMENT_FLOOR} if source == "article_sentiment" else {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _to_observations(raw: list[dict], horizon: int) -> list[dict]:
    rows = []
    dropped = 0
    for r in raw:
        reference, target = (
            (r["prev_close"], r["close"])
            if horizon == 0
            else (r["close"], r["next_close"])
        )
        if reference is None or target is None:
            dropped += 1
            continue
        rows.append(
            {
                "ticker": r["ticker"],
                "date": r["date"],
                "sentiment": float(r["sentiment"]),
                "actual_up": float(target) > float(reference),
            }
        )
    if dropped:
        edge = "prior" if horizon == 0 else "next"
        print(
            f"  Dropped {dropped} ticker/day row(s) with no {edge} trading-day close available (backfill edge or weekend/holiday gap)."
        )
    return rows


def _split(rows: list[dict], seed: int) -> tuple[list[dict], list[dict]]:
    shuffled = rows[:]
    random.Random(seed).shuffle(shuffled)
    cutoff = round(len(shuffled) * _SPLIT_FRACTION)
    return shuffled[:cutoff], shuffled[cutoff:]


def _base_rate(rows: list[dict]) -> float | None:
    if not rows:
        return None
    return sum(r["actual_up"] for r in rows) / len(rows)


def _accuracy(rows: list[dict], threshold: float) -> float | None:
    if not rows:
        return None
    correct = sum(1 for r in rows if (r["sentiment"] >= threshold) == r["actual_up"])
    return correct / len(rows)


def _sweep(train: list[dict], cv: list[dict]) -> list[dict]:
    return [
        {
            "threshold": t,
            "train_n": len(train),
            "train_accuracy": _accuracy(train, t),
            "cv_n": len(cv),
            "cv_accuracy": _accuracy(cv, t),
        }
        for t in _THRESHOLDS
    ]


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _print_table(
    source: str, horizon: int, train: list[dict], cv: list[dict], sweep_rows: list[dict]
) -> None:
    print(f"\n=== source={source} horizon={horizon} ===")
    print(
        f"  train n={len(train)} (base rate {_fmt_pct(_base_rate(train))})   "
        f"cv n={len(cv)} (base rate {_fmt_pct(_base_rate(cv))})"
    )
    if len(train) < _MIN_SPLIT_N or len(cv) < _MIN_SPLIT_N:
        print(
            f"  WARNING: a split below {_MIN_SPLIT_N} observations produces accuracy figures "
            "that are mostly noise - do not read these as 'the best threshold'."
        )
    print(f"\n  {'threshold':<10}{'train_acc':<12}{'cv_acc':<12}")
    for row in sweep_rows:
        print(
            f"  {row['threshold']:<10}{_fmt_pct(row['train_accuracy']):<12}{_fmt_pct(row['cv_accuracy']):<12}"
        )


def _write_csv(path: Path, all_rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["source", "horizon", "threshold", "train_n", "train_accuracy", "cv_n", "cv_accuracy"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sweep sentiment as a decision boundary (predict up if sentiment >= threshold) "
        "against actual daily price direction, over an 80/20 train/cross-validation split."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Fixed seed for the random 80/20 train/CV split (default 42).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).parent / "eval",
        help="Directory to write threshold_sweep.csv into (default: lambda/sentiment_analysis/eval/).",
    )
    args = parser.parse_args()

    all_csv_rows = []
    for source in _SOURCES:
        raw = _fetch_raw(source)
        if not raw:
            print(f"\n=== source={source} ===\n  No rows found - skipping.")
            continue
        for horizon in _HORIZONS:
            rows = _to_observations(raw, horizon)
            if not rows:
                print(f"\n=== source={source} horizon={horizon} ===\n  No usable rows - skipping.")
                continue
            train, cv = _split(rows, args.seed)
            sweep_rows = _sweep(train, cv)
            _print_table(source, horizon, train, cv, sweep_rows)
            for row in sweep_rows:
                all_csv_rows.append({"source": source, "horizon": horizon, **row})

    if not all_csv_rows:
        raise SystemExit(
            "No overlapping sentiment/price rows found for any source - run lambda/price_backfill "
            "and lambda/sentiment_analysis/run.py first."
        )

    out_path = args.out_dir / "threshold_sweep.csv"
    _write_csv(out_path, all_csv_rows)
    print(f"\nWrote {len(all_csv_rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
