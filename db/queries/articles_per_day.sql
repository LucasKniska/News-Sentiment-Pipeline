-- Article volume by publish date; useful for spotting gaps in historical
-- coverage before the Week 5-6 backtest needs a continuous date range.
SELECT
    date_trunc('day', datetime) AS publish_date,
    COUNT(*) AS article_count
FROM articles
GROUP BY 1
ORDER BY 1 DESC;
