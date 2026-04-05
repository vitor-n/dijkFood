resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnet"
  subnet_ids = var.database_subnet_ids

  tags = { Name = "${var.project_name}-db-subnet-group" }
}

resource "aws_db_instance" "main" {
  identifier     = "${var.project_name}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.instance_class

  db_name  = "dijkfood"
  username = var.db_username
  password = var.db_password
  port     = 5432

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.security_group_id]

  backup_retention_period = 7
  skip_final_snapshot     = true
  deletion_protection     = false

  auto_minor_version_upgrade = false

  tags = {
    Name      = "${var.project_name}-database"
    Component = "database"
  }
}
