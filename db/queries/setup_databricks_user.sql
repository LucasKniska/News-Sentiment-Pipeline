
CREATE USER databricks_ro WITH PASSWORD 'CHANGE_ME_AFTER_RUNNING';
GRANT SELECT ON articles, signals, daily_prices, article_sentiment TO databricks_ro;
