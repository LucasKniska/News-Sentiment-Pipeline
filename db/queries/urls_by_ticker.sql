-- Change 'AAPL' to whichever ticker you want.
SELECT url
FROM articles
WHERE 'AAPL' = ANY(tickers)
ORDER BY datetime DESC;
