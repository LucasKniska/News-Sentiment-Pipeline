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

# TEMPORARY - DELETE THIS RESOURCE once RESUME_SENTIMENT_BACKFILL.md's
# 2026-07-07 through 2026-07-31 range shows full coverage (check via the
# coverage query in that file), then remove this block and `terraform apply`.
#
# Groq's account-wide daily token quota (TPD) means the July sentiment
# backfill can only make a bit more progress each day, once the quota resets
# - see RESUME_SENTIMENT_BACKFILL.md. Rather than a human watching console
# output and re-running local_run.py by hand every morning, this invokes the
# same deployed sentiment_analysis Lambda with a fixed backfill_range event;
# run_backfill() (lambda/sentiment_analysis/run.py) figures out which dates
# in the range still need work and stops itself once it hits the day's quota
# wall, so this is safe to just leave running unattended.
#
# 5am ET - one hour after the live sentiment_analysis_daily run above, so the
# production daily job always gets first claim on the shared Groq quota. That
# hour of separation also makes the two schedules' Lambda invocations mutually
# exclusive in time, since each is capped at the 900s timeout below.
resource "aws_scheduler_schedule" "sentiment_backfill_daily" {
  name = "news-sentiment-backfill-daily"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = "cron(0 5 * * ? *)"
  schedule_expression_timezone = "America/New_York"

  target {
    arn      = aws_lambda_function.sentiment_analysis.arn
    role_arn = aws_iam_role.scheduler_invoke_lambda.arn

    input = jsonencode({
      backfill_range = ["2026-07-07", "2026-07-31"]
    })

    # Same reasoning as sentiment_analysis_daily above - signals has no
    # unique business key, so an overlapping retry could double-insert.
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
