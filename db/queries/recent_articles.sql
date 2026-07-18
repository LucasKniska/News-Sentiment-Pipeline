-- Verification query for a deployed Lambda smoke-test invoke: confirms the
-- write landed without needing to know exact article ids beforehand.
SELECT id, headline, tickers, ingested_at
FROM articles
WHERE ingested_at > now() - interval '15 minutes'
ORDER BY ingested_at DESC;
