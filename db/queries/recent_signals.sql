-- Verification query for a local_run.py invocation: confirms writes landed
-- without needing to know exact signal ids beforehand.
SELECT id, ticker, timestamp, event_type, sentiment, involvement, article_ids
FROM signals
WHERE timestamp > now() - interval '15 minutes'
ORDER BY timestamp DESC;
