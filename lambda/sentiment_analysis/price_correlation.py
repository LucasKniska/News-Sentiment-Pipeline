import argparse
import statistics
import sys

from dotenv import load_dotenv

# Windows terminals default stdout to the cp1252 codepage, which can't encode
# every character article text may contain (e.g. currency symbols).
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

from db import get_connection  # noqa: E402  (must import after load_dotenv, see local_run.py)

# Below this involvement, an article barely mentions the ticker - same floor
# run_eval.py uses to treat a low-involvement extraction as a "skip" rather
# than a real opinion (see run_eval.py's _SKIP_INVOLVEMENT_THRESHOLD). Used
# here as an aggregation filter, not a second sweep dimension - a 2-D grid
# over threshold x involvement floor would be worse than useless at this n.
_INVOLVEMENT_FLOOR = 0.3

_THRESHOLDS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]

# Pulls from article_sentiment (raw per-article extractor output, one row per
# article/ticker) rather than signals (LLM-combined per run, only 30 rows
# total right now) - aggregating raw extractions ourselves gives more usable
# rows and skips re-deriving signals' article_ids -> articles.datetime join.
# LAG/LEAD give same-day and forward-day baselines in one pass; rows at either
# end of a ticker's price history (or across a weekend/holiday gap) naturally
# come back NULL and get dropped in Python rather than silently inner-joined
# away.
_QUERY = """
    WITH daily_sentiment AS (
        SELECT
            s.ticker,
            a.datetime::date AS date,
            SUM(s.sentiment * s.involvement) / SUM(s.involvement) AS sentiment,
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
    SELECT ds.ticker, ds.date, ds.sentiment, ds.n_articles, pm.prev_close, pm.close, pm.next_close
    FROM daily_sentiment ds
    JOIN price_moves pm ON pm.ticker = ds.ticker AND pm.date = ds.date
    ORDER BY ds.ticker, ds.date
"""


def _load_rows(horizon: int) -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_QUERY, {"involvement_floor": _INVOLVEMENT_FLOOR})
            columns = [desc[0] for desc in cur.description]
            raw = [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()

    rows = []
    dropped = 0
    for r in raw:
        reference, target = (r["prev_close"], r["close"]) if horizon == 0 else (r["close"], r["next_close"])
        if reference is None or target is None:
            dropped += 1
            continue
        rows.append({
            "ticker": r["ticker"],
            "date": r["date"],
            "sentiment": float(r["sentiment"]),
            "n_articles": r["n_articles"],
            "actual_up": float(target) > float(reference),
        })

    if dropped:
        edge = "prior" if horizon == 0 else "next"
        print(f"Dropped {dropped} ticker/day row(s) with no {edge} trading-day close available (backfill edge or weekend/holiday gap).")
    return rows


def _report_by_ticker(rows: list[dict]) -> None:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["ticker"]] = counts.get(r["ticker"], 0) + 1
    print("\nObservations per ticker (small counts here mean everything below is noisy):")
    for ticker, n in sorted(counts.items()):
        print(f"  {ticker:<6}{n}")


def _report_correlation(rows: list[dict]) -> None:
    if len(rows) < 3:
        print("\nToo few observations for a correlation coefficient.")
        return
    sentiments = [r["sentiment"] for r in rows]
    actual_up = [1.0 if r["actual_up"] else 0.0 for r in rows]
    r = statistics.correlation(sentiments, actual_up)
    print(f"\nPearson correlation, continuous sentiment vs. up=1/down=0, n={len(rows)}: {r:.3f}")


def _report_threshold_sweep(rows: list[dict]) -> None:
    base_rate = sum(r["actual_up"] for r in rows) / len(rows)
    print(f"\nBase rate (share of days actually up): {base_rate:.1%} over {len(rows)} days - compare accuracy below against this, not against 50%.")
    print(f"\n{'threshold':<10}{'n':<6}{'excluded':<10}{'accuracy':<10}")
    for t in _THRESHOLDS:
        kept = [(r["sentiment"] >= t, r["actual_up"]) for r in rows if abs(r["sentiment"]) >= t]
        if not kept:
            print(f"{t:<10}{0:<6}{len(rows):<10}{'n/a':<10}")
            continue
        accuracy = sum(1 for pred, actual in kept if pred == actual) / len(kept)
        print(f"{t:<10}{len(kept):<6}{len(rows) - len(kept):<10}{accuracy:<10.1%}")
    print(
        "\nn shrinks at every row above (fewer days clear the threshold) - do not read this as "
        "'the best threshold', an accuracy figure from a handful of days is noise. The fix is more "
        "backfilled price history (lambda/price_backfill), not a finer threshold grid."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Correlate AI-extracted sentiment direction against actual daily price direction.")
    parser.add_argument(
        "--horizon", type=int, choices=[0, 1], default=0,
        help="0 (default): sentiment from day D's articles vs. close(D) over close(D-1) - tests whether "
             "extraction reads a day's news the same direction the market moved that day. "
             "1: vs. close(D+1) over close(D) - a forward/tradeable signal, needs far more data than we have to mean anything.",
    )
    args = parser.parse_args()

    rows = _load_rows(args.horizon)
    if not rows:
        raise SystemExit("No overlapping sentiment/price rows found - run lambda/price_backfill and lambda/sentiment_analysis/run.py first.")

    print(f"Loaded {len(rows)} ticker/day observations (involvement floor {_INVOLVEMENT_FLOOR}, horizon={args.horizon}).")
    _report_by_ticker(rows)
    _report_correlation(rows)
    _report_threshold_sweep(rows)


if __name__ == "__main__":
    main()
