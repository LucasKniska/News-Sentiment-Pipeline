-- All per-article sentiment calls from the past 24 hours, across every
-- tracked ticker - the raw granular view (article_sentiment), not the
-- blended daily signal in `signals`. Change the interval below for a
-- longer/shorter window.
SELECT
    a.datetime AS published,
    s.ticker,
    s.sentiment,
    s.involvement,
    a.headline,
    a.url
FROM article_sentiment s
JOIN articles a ON a.id = s.article_id
WHERE s.timestamp > now() - interval '1 day'
ORDER BY s.timestamp DESC;
