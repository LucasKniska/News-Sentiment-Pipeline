
CREATE USER lambda_sentiment;
GRANT rds_iam TO lambda_sentiment;
GRANT SELECT ON articles TO lambda_sentiment;
GRANT SELECT, INSERT ON signals TO lambda_sentiment;
-- signals.id is BIGSERIAL - table-level INSERT doesn't imply the right to call
-- nextval() on its backing sequence, that needs a separate grant. articles.id
-- (lambda_ingestion's table) is a plain BIGINT PK supplied by Finnhub, so this
-- has no precedent there.
GRANT USAGE ON SEQUENCE signals_id_seq TO lambda_sentiment;
GRANT SELECT, INSERT, UPDATE ON article_sentiment TO lambda_sentiment;
