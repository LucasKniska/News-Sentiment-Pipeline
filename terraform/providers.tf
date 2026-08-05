provider "aws" {
  profile = "terraform-user"
  region  = "us-east-1"

  # Applied to every taggable resource this provider manages - lets
  # resource_group.tf gather the whole project via a tag query instead of
  # an explicit, easy-to-forget-to-update resource list.
  default_tags {
    tags = {
      Project = "news-sentiment-pipeline"
    }
  }
}

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.94"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.4"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

