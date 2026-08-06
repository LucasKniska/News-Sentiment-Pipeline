-- Same idea as ticker_sentiment_history.sql, but the raw per-article calls
-- (article_sentiment) behind the blended signal, with headlines attached so
-- you can actually see what drove each move. Change 'AAPL' and the interval
-- below to whichever ticker/lookback you want.
SELECT
    a.datetime AS published,
    s.sentiment,
    s.involvement,
    a.headline,
    a.url
FROM article_sentiment s
JOIN articles a ON a.id = s.article_id
WHERE s.ticker = 'AAPL'
  AND a.datetime > now() - interval '30 days'
ORDER BY a.datetime ASC;
