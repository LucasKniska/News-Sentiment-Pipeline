# Puts both Lambdas on a daily schedule via EventBridge Scheduler (a separate,
# newer service from the plain EventBridge "rules" used previously here -
# aws_cloudwatch_event_rule's schedule_expression has no timezone concept, it
# only understands UTC cron, so "1am ET" would silently become "12am ET" or
# "2am ET" for half the year across the EST/EDT switch. schedule_expression_timezone
# below makes AWS handle that conversion, so the cron expressions can just say
# what they mean: 1am and 4am US Eastern, year-round.
#
# Ordering: sentiment_analysis reads articles ingestion wrote, so it has to run
# after news_ingestion has had time to finish - 3 hours of headroom (1am vs
# 4am ET) comfortably covers news_ingestion's worst-case 900s (15min) Lambda
# timeout even with retries, while both still land well before US markets
# open at 9:30am ET.
#
# EventBridge Scheduler needs its own IAM role (unlike the old rules-based
# approach, which used a simple resource-based aws_lambda_permission) - the
# scheduler service assumes this role to invoke each target Lambda, so the
# role needs both a trust policy for scheduler.amazonaws.com and an explicit
# lambda:InvokeFunction grant on the specific function ARNs.
data "aws_iam_policy_document" "scheduler_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler_invoke_lambda" {
  name               = "news-sentiment-scheduler-invoke-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_role.json
}

data "aws_iam_policy_document" "scheduler_invoke_lambda" {
  statement {
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.news_ingestion.arn,
      aws_lambda_function.sentiment_analysis.arn,
    ]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name   = "news-sentiment-scheduler-invoke"
  role   = aws_iam_role.scheduler_invoke_lambda.id
  policy = data.aws_iam_policy_document.scheduler_invoke_lambda.json
}

resource "aws_scheduler_schedule" "news_ingestion_daily" {
  name = "news-sentiment-ingestion-daily"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = "cron(0 1 * * ? *)"
  schedule_expression_timezone = "America/New_York"

  target {
    arn      = aws_lambda_function.news_ingestion.arn
    role_arn = aws_iam_role.scheduler_invoke_lambda.arn

    # EventBridge Scheduler's default retry policy (185 attempts over 24h) is far
    # more aggressive than the old rules-based schedule had. A sequential retry of
    # this Lambda is harmless (upsert_articles is idempotent), but disable retries
    # anyway since a stuck invocation retrying for a day serves no purpose here -
    # the next day's scheduled run supersedes it regardless.
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}

resource "aws_scheduler_schedule" "sentiment_analysis_daily" {
  name = "news-sentiment-analysis-daily"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = "cron(0 4 * * ? *)"
  schedule_expression_timezone = "America/New_York"

  target {
    arn      = aws_lambda_function.sentiment_analysis.arn
    role_arn = aws_iam_role.scheduler_invoke_lambda.arn

    # Disabled for a stronger reason than news_ingestion's: signals has no
    # unique business key (see db/schema.sql), so two overlapping invocations
    # (e.g. a retry firing while the original run is still in flight) would
    # both see no prior signal for the same new articles and both insert -
    # a real double-count, not just wasted work.
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
