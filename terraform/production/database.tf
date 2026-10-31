resource "aws_security_group" "db" {
  name        = "${local.name}-db-sg"
  description = "Access to RDS PostgreSQL from EKS cluster"
  vpc_id      = aws_vpc.this.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_eks_cluster.this.vpc_config[0].cluster_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name}-db-sg"
  }
}

resource "aws_db_subnet_group" "this" {
  name       = "${local.name}-db-subnet-group"
  subnet_ids = aws_subnet.database[*].id

  tags = {
    Name = "${local.name}-db-subnet-group"
  }
}

resource "random_password" "db_password" {
  length  = 24
  special = false
}

resource "aws_db_instance" "postgres" {
  identifier        = "${local.name}-postgres"
  engine            = "postgres"
  engine_version    = var.postgres_engine_version
  instance_class    = var.db_instance_class
  allocated_storage = 50
  storage_type      = "gp3"

  db_name  = "legal_checker_prod"
  username = "legal_admin"
  password = random_password.db_password.result

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  skip_final_snapshot    = true

  tags = {
    Name        = "${local.name}-postgres"
    Environment = var.environment
  }
}
