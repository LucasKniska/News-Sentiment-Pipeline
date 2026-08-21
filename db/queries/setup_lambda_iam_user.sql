
CREATE USER lambda_ingestion;
GRANT rds_iam TO lambda_ingestion;
GRANT SELECT, INSERT, UPDATE ON articles TO lambda_ingestion;
GRANT SELECT, INSERT, UPDATE ON daily_prices TO lambda_ingestion;
