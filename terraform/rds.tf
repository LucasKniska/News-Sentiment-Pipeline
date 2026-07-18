data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
}

data "http" "my_ip" {
  url = "https://checkip.amazonaws.com"
}

resource "aws_db_subnet_group" "postgres" {
  name       = "news-sentiment-db-subnet-group"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_security_group" "rds" {
  name        = "news-sentiment-rds-sg"
  description = "Allow Postgres access from my IP"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["${chomp(data.http.my_ip.response_body)}/32"]
  }

  ingress {
    description = "Temporary: non-VPC Lambda has no stable CIDR to scope this to. Revisit if/when Lambda moves into the VPC behind a NAT gateway. Access is gated by IAM DB auth, not by network scoping."
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "postgres" {
  identifier                          = "news-sentiment-db"
  engine                              = "postgres"
  engine_version                      = "16"
  instance_class                      = "db.t3.micro"
  allocated_storage                   = 20
  db_name                             = "news_sentiment"
  username                            = var.db_username
  password                            = var.db_password
  db_subnet_group_name                = aws_db_subnet_group.postgres.name
  vpc_security_group_ids              = [aws_security_group.rds.id]
  publicly_accessible                 = true
  iam_database_authentication_enabled = true
  apply_immediately                   = true
  skip_final_snapshot                 = true
}
