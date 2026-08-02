data "archive_file" "news_ingestion" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/news_ingestion/build"
  output_path = "${path.module}/../lambda/news_ingestion/build.zip"
}

data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  # Dedicated least-privilege Postgres role for this Lambda, provisioned via
  # db/queries/setup_lambda_iam_user.sql - not var.db_username, which is the
  # broader admin-ish user used for schema changes and laptop access.
  lambda_db_username = "lambda_ingestion"

  # Single source of truth for which tickers this project tracks/signals on.
  # Passed to every Lambda via TICKERS so ingestion and sentiment extraction
  # can't drift out of sync.
  tracked_tickers = ["NVDA", "LMT", "XOM", "AUR", "AAPL"]
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "news-sentiment-ingestion-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "rds_connect" {
  statement {
    effect  = "Allow"
    actions = ["rds-db:connect"]
    resources = [
      "arn:${data.aws_partition.current.partition}:rds-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.postgres.resource_id}/${local.lambda_db_username}"
    ]
  }
}

resource "aws_iam_role_policy" "rds_connect" {
  name   = "news-sentiment-ingestion-rds-connect"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.rds_connect.json
}

resource "aws_cloudwatch_log_group" "news_ingestion" {
  name              = "/aws/lambda/news-sentiment-ingestion"
  retention_in_days = 14
}

resource "aws_lambda_function" "news_ingestion" {
  function_name = "news-sentiment-ingestion"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.13"
  architectures = ["x86_64"]

  filename         = data.archive_file.news_ingestion.output_path
  source_code_hash = data.archive_file.news_ingestion.output_base64sha256

  memory_size = 512
  # Scraping is sequential per-article with no explicit per-fetch timeout;
  # the AAPL smoke test alone pulls ~176 articles, so this uses the max.
  timeout = 900

  environment {
    variables = {
      FINNHUB_API_KEY = var.finnhub_api_key
      PGHOST          = aws_db_instance.postgres.address # not .endpoint, which is "host:port"
      PGPORT          = tostring(aws_db_instance.postgres.port)
      PGDATABASE      = aws_db_instance.postgres.db_name
      PGUSER          = local.lambda_db_username
      PG_IAM_AUTH     = "true"
      TICKERS         = join(",", local.tracked_tickers)
    }
  }

  # Not VPC-attached: staying outside the VPC keeps default internet egress
  # for the Finnhub API + arbitrary news-site scraping without a NAT gateway.
  # RDS access instead relies on IAM DB auth (see db.py's PG_IAM_AUTH branch)
  # rather than network scoping - see the security group note in rds.tf.

  depends_on = [aws_cloudwatch_log_group.news_ingestion]
}
