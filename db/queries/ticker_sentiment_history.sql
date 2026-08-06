-- How one ticker's blended daily sentiment (the `signals` table - one row per
-- calculation run) has tracked over time. Change 'AAPL' and the interval
-- below to whichever ticker/lookback you want.
SELECT
    timestamp,
    event_type,
    sentiment,
    involvement,
    array_length(article_ids, 1) AS article_count
FROM signals
WHERE ticker = 'AAPL'
  AND timestamp > now() - interval '30 days'
ORDER BY timestamp ASC;
