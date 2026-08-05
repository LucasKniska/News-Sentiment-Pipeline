data "archive_file" "sentiment_analysis" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/sentiment_analysis/build"
  output_path = "${path.module}/../lambda/sentiment_analysis/build.zip"
}

resource "aws_iam_role" "sentiment_lambda_exec" {
  name               = "news-sentiment-analysis-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "sentiment_lambda_basic_execution" {
  role       = aws_iam_role.sentiment_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "sentiment_rds_connect" {
  statement {
    effect  = "Allow"
    actions = ["rds-db:connect"]
    resources = [
      "arn:${data.aws_partition.current.partition}:rds-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.postgres.resource_id}/${local.sentiment_lambda_db_username}"
    ]
  }
}

resource "aws_iam_role_policy" "sentiment_rds_connect" {
  name   = "news-sentiment-analysis-rds-connect"
  role   = aws_iam_role.sentiment_lambda_exec.id
  policy = data.aws_iam_policy_document.sentiment_rds_connect.json
}

resource "aws_cloudwatch_log_group" "sentiment_analysis" {
  name              = "/aws/lambda/news-sentiment-analysis"
  retention_in_days = 14
}

resource "aws_lambda_function" "sentiment_analysis" {
  function_name = "news-sentiment-analysis"
  role          = aws_iam_role.sentiment_lambda_exec.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.13"
  architectures = ["x86_64"]

  filename         = data.archive_file.sentiment_analysis.output_path
  source_code_hash = data.archive_file.sentiment_analysis.output_base64sha256

  memory_size = 512
  # Same reasoning as news_ingestion: extraction fans out per-article LLM
  # calls (run.py's ThreadPoolExecutor), so worst-case runtime scales with a
  # busy day's article count rather than being predictable up front.
  timeout = 900

  environment {
    variables = {
      GROQ_API_KEY      = var.groq_api_key
      ANTHROPIC_API_KEY = var.anthropic_api_key
      PGHOST            = aws_db_instance.postgres.address
      PGPORT            = tostring(aws_db_instance.postgres.port)
      PGDATABASE        = aws_db_instance.postgres.db_name
      PGUSER            = local.sentiment_lambda_db_username
      PG_IAM_AUTH       = "true"
      TICKERS           = join(",", local.tracked_tickers)
    }
  }

  # Not VPC-attached, same reasoning as news_ingestion: no NAT gateway means
  # no stable egress IP if this were VPC-attached, and it needs open internet
  # egress to reach the Groq/Anthropic APIs anyway. RDS access relies on IAM
  # DB auth rather than network scoping - see rds.tf's security group note.

  depends_on = [aws_cloudwatch_log_group.sentiment_analysis]
}
