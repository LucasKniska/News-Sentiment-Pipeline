-- Quick sanity check after a Lambda invoke or schema change.
SELECT 'articles' AS table_name, COUNT(*) AS row_count FROM articles
UNION ALL
SELECT 'signals', COUNT(*) FROM signals;
