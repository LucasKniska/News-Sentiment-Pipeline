-- Current sentiment snapshot: the most recent signals row per tracked ticker,
-- regardless of when it ran. signals is append-only (one row per calculation
-- run, not per article), so "latest state" means the newest row per ticker,
-- not a single table-wide MAX(timestamp).
SELECT DISTINCT ON (ticker)
    ticker,
    timestamp,
    event_type,
    sentiment,
    involvement,
    array_length(article_ids, 1) AS article_count
FROM signals
ORDER BY ticker, timestamp DESC;
