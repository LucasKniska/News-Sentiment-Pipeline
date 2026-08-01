# Puts news_ingestion on an automatic daily schedule via EventBridge (formerly
# CloudWatch Events). Three pieces are required: a rule (the "when"), a target
# (the "what to invoke" - our existing Lambda, no event payload so it falls
# back to handler.py's DEFAULT_TICKERS), and a permission (EventBridge is a
# separate AWS service from Lambda, so it needs explicit resource-based
# permission to invoke the function - IAM roles alone don't cover this).
resource "aws_cloudwatch_event_rule" "news_ingestion_daily" {
  name = "news-sentiment-ingestion-daily"
  # 11:00 UTC = 6-7am US Eastern (pre-market), so each day's run picks up
  # overnight news before the trading day starts. cron(), not rate(), so the
  # time of day is pinned instead of drifting relative to whenever this was
  # first applied.
  schedule_expression = "cron(0 11 * * ? *)"
}

resource "aws_cloudwatch_event_target" "news_ingestion_daily" {
  rule = aws_cloudwatch_event_rule.news_ingestion_daily.name
  arn  = aws_lambda_function.news_ingestion.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.news_ingestion.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.news_ingestion_daily.arn
}
