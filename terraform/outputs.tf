output "rds_endpoint" {
  value = aws_db_instance.postgres.endpoint
}

output "api_endpoint" {
  value = aws_apigatewayv2_stage.default.invoke_url
}
