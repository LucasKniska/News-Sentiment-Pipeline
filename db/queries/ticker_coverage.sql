-- Per-ticker article count and ingestion freshness; unnest since tickers is
-- an array column. Useful for spotting sparse or stale tickers before deciding
-- whether to rerun ingestion for one ticker vs. a full DEFAULT_TICKERS pass.
SELECT
    ticker,
    COUNT(*) AS article_count,
    MAX(ingested_at) AS last_ingested,
    MAX(datetime) AS latest_article_datetime
FROM articles, unnest(tickers) AS ticker
GROUP BY ticker
ORDER BY article_count DESC;
