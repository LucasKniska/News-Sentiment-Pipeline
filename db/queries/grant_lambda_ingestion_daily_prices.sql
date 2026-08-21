-- daily_prices was added after lambda_ingestion was provisioned (setup_lambda_iam_user.sql
-- only ever granted articles), so the deployed Lambda's upsert_daily_price() has been
-- failing with InsufficientPrivilege on every live invocation since 2026-08-08.
GRANT SELECT, INSERT, UPDATE ON daily_prices TO lambda_ingestion;
