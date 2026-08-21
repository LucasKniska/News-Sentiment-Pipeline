# lambda/dashboard_embed has zero third-party dependencies (stdlib urllib
# only, deliberately, to avoid needing a build.ps1/wheel step for a Lambda
# that just makes three outbound HTTPS calls) - archive_file zips handler.py
# directly rather than a build/ output dir, so a stray local .env can never
# end up in the deployment package.
data "archive_file" "dashboard_embed" {
  type        = "zip"
  source_file = "${path.module}/../lambda/dashboard_embed/handler.py"
  output_path = "${path.module}/../lambda/dashboard_embed/build.zip"
}

resource "aws_iam_role" "dashboard_embed_lambda_exec" {
  name               = "news-sentiment-dashboard-embed-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "dashboard_embed_lambda_basic_execution" {
  role       = aws_iam_role.dashboard_embed_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "dashboard_embed" {
  name              = "/aws/lambda/news-sentiment-dashboard-embed"
  retention_in_days = 14
}

resource "aws_lambda_function" "dashboard_embed" {
  function_name = "news-sentiment-dashboard-embed"
  role          = aws_iam_role.dashboard_embed_lambda_exec.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.13"
  architectures = ["x86_64"]

  filename         = data.archive_file.dashboard_embed.output_path
  source_code_hash = data.archive_file.dashboard_embed.output_base64sha256

  # Three sequential outbound HTTPS calls to Databricks, no DB/AWS SDK work -
  # small and fast, same reasoning as the api Lambda's sizing.
  memory_size = 128
  timeout     = 20

  environment {
    variables = {
      DATABRICKS_HOST             = var.databricks_workspace_host
      DATABRICKS_ORG_ID           = var.databricks_org_id
      DATABRICKS_DASHBOARD_ID     = var.databricks_dashboard_id
      DATABRICKS_SP_CLIENT_ID     = var.databricks_sp_client_id
      DATABRICKS_SP_CLIENT_SECRET = var.databricks_sp_client_secret
    }
  }

  # Not VPC-attached: needs open internet egress to reach Databricks, and has
  # no AWS resource (RDS or otherwise) to reach privately in the first place.

  depends_on = [aws_cloudwatch_log_group.dashboard_embed]
}

resource "aws_apigatewayv2_integration" "dashboard_embed" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.dashboard_embed.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "dashboard_token" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "GET /dashboard-token"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard_embed.id}"
}

resource "aws_lambda_permission" "dashboard_embed_api_gw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dashboard_embed.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
