data "aws_vpc" "main" {
  id = "vpc-0a31af5427b9b7d74"
}

output "vpc_cidr" {
  value = data.aws_vpc.main.cidr_block
}