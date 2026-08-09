
CREATE USER api_read;
GRANT rds_iam TO api_read;
GRANT SELECT ON signals, articles TO api_read;
