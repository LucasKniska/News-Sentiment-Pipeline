# Groups every resource tagged Project=news-sentiment-pipeline (see the
# provider's default_tags in providers.tf) so the whole project's AWS
# footprint - RDS, the Lambda + its role/log group, the EventBridge rule,
# etc. - can be viewed together in the Resource Groups console regardless of
# which service each piece belongs to.
resource "aws_resourcegroups_group" "project" {
  name = "news-sentiment-pipeline"

  resource_query {
    query = jsonencode({
      ResourceTypeFilters = ["AWS::AllSupported"]
      TagFilters = [
        {
          Key    = "Project"
          Values = ["news-sentiment-pipeline"]
        }
      ]
    })
  }
}
