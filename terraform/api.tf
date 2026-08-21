data "archive_file" "api" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/api/build"
  output_path = "${path.module}/../lambda/api/build.zip"
}

locals {
  # Must match the username already created by db/queries/setup_api_iam_user.sql
  # (CREATE USER api_read; GRANT rds_iam TO api_read; GRANT SELECT ON signals,
  # articles TO api_read;) - unlike lambda_ingestion/lambda_sentiment, this
  # role was provisioned ahead of this Lambda existing.
  api_lambda_db_username = "api_read"
}

resource "aws_iam_role" "api_lambda_exec" {
  name               = "news-sentiment-api-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "api_lambda_basic_execution" {
  role       = aws_iam_role.api_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "api_rds_connect" {
  statement {
    effect  = "Allow"
    actions = ["rds-db:connect"]
    resources = [
      "arn:${data.aws_partition.current.partition}:rds-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.postgres.resource_id}/${local.api_lambda_db_username}"
    ]
  }
}

resource "aws_iam_role_policy" "api_rds_connect" {
  name   = "news-sentiment-api-rds-connect"
  role   = aws_iam_role.api_lambda_exec.id
  policy = data.aws_iam_policy_document.api_rds_connect.json
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/news-sentiment-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name = "news-sentiment-api"
  role          = aws_iam_role.api_lambda_exec.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.13"
  architectures = ["x86_64"]

  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256

  # Unlike news_ingestion/sentiment_analysis, this Lambda does one fast DB
  # query with no scraping/LLM calls, so it doesn't need their 512MB/900s
  # sizing.
  memory_size = 256
  timeout     = 30

  # No reserved_concurrent_executions: this AWS account's Lambda concurrency
  # limit is only 10 total (aws lambda get-account-settings), and AWS
  # requires >=10 to stay unreserved account-wide - so any positive
  # reservation here fails outright. Falls back to the API Gateway throttle
  # below as the only rate-limiting layer; revisit if the account limit is
  # ever raised (AWS support quota increase).

  environment {
    variables = {
      PGHOST      = aws_db_instance.postgres.address
      PGPORT      = tostring(aws_db_instance.postgres.port)
      PGDATABASE  = aws_db_instance.postgres.db_name
      PGUSER      = local.api_lambda_db_username
      PG_IAM_AUTH = "true"
    }
  }

  # Not VPC-attached, same reasoning as the other two Lambdas - relies on IAM
  # DB auth rather than network scoping (see rds.tf's security group note).

  depends_on = [aws_cloudwatch_log_group.api]
}

resource "aws_apigatewayv2_api" "api" {
  name          = "news-sentiment-api"
  protocol_type = "HTTP"

  # Permissive: this is a public, read-only endpoint, and the eventual
  # GitHub Pages frontend will call it cross-origin.
  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET"]
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "signals_recent" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "GET /signals/recent"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  # Rejects excess requests at the API Gateway layer (a 429, no Lambda
  # invocation, no cost) before they ever reach the Lambda. This is the real
  # dollar-cost ceiling: at 2 req/sec sustained 24/7 for a month (~5.2M
  # requests), worst case is roughly $6-7 combined API Gateway + Lambda cost.
  # Tune upward if real traffic ever gets throttled.
  default_route_settings {
    throttling_rate_limit  = 4
    throttling_burst_limit = 8
  }
}

resource "aws_lambda_permission" "api_gw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
