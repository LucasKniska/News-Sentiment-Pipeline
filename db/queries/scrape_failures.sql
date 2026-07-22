-- Scraper health check: NULL text means trafilatura AND the Finnhub summary
-- fallback both came up empty; short non-NULL text usually means it fell back
-- to the summary instead of a full-article scrape. Useful for gauging how
-- often paywalls/bot-blocking are degrading article quality.
SELECT
    id,
    headline,
    url,
    datetime,
    COALESCE(length(text), 0) AS text_length
FROM articles
WHERE text IS NULL OR length(text) < 200
ORDER BY datetime DESC;
