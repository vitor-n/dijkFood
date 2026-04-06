locals {
  services = [
    "core-api",
    "routing-service",
    "tracking-service",
    "order-service"
  ]
  database_url = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${module.rds.endpoint}:5432/dijkfood"
}

# ──────────────────────────────────────────────
#  Networking (VPC, subnets, IGW, NAT)
# ──────────────────────────────────────────────

module "networking" {
  source = "./modules/networking"

  project_name       = var.project_name
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
}

# ──────────────────────────────────────────────
#  Security Groups (root level — no circular deps)
# ──────────────────────────────────────────────

resource "aws_security_group" "ecs_tasks" {
  name_prefix = "${var.project_name}-ecs-"
  description = "Allow inbound from ALB to ECS tasks"
  vpc_id      = module.networking.vpc_id

  ingress {
    protocol        = "tcp"
    from_port       = 8000
    to_port         = 8003
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle { create_before_destroy = true }
  tags = { Name = "${var.project_name}-ecs-sg" }
}

resource "aws_security_group" "alb" {
  name_prefix = "${var.project_name}-alb-"
  description = "Allow HTTP/HTTPS inbound to ALB"
  vpc_id      = module.networking.vpc_id

  ingress {
    protocol    = "tcp"
    from_port   = 80
    to_port     = 80
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle { create_before_destroy = true }
  tags = { Name = "${var.project_name}-alb-sg" }
}

resource "aws_security_group" "rds" {
  name_prefix = "${var.project_name}-rds-"
  description = "Allow PostgreSQL from ECS tasks"
  vpc_id      = module.networking.vpc_id

  ingress {
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle { create_before_destroy = true }
  tags = { Name = "${var.project_name}-rds-sg" }
}

# ──────────────────────────────────────────────
#  ECR — Container Registries
# ──────────────────────────────────────────────

module "ecr" {
  source = "./modules/ecr"

  project_name = var.project_name
  services     = local.services
}

# ──────────────────────────────────────────────
#  S3 — Graph Data Bucket
# ──────────────────────────────────────────────

module "s3" {
  source = "./modules/s3"

  project_name = var.project_name
  environment  = var.environment
}

# ──────────────────────────────────────────────
#  RDS — PostgreSQL
# ──────────────────────────────────────────────

module "rds" {
  source = "./modules/rds"

  project_name        = var.project_name
  environment         = var.environment
  database_subnet_ids = module.networking.database_subnet_ids
  security_group_id   = aws_security_group.rds.id
  db_username         = var.db_username
  db_password         = var.db_password
  instance_class      = var.db_instance_class
  multi_az            = var.db_multi_az
}

# ──────────────────────────────────────────────
#  DynamoDB — Courier Position Tracking
# ──────────────────────────────────────────────

module "dynamodb" {
  source = "./modules/dynamodb"

  project_name = var.project_name
  environment  = var.environment
}

# ──────────────────────────────────────────────
#  ALB — Application Load Balancer
# ──────────────────────────────────────────────

module "alb" {
  source = "./modules/alb"

  project_name          = var.project_name
  vpc_id                = module.networking.vpc_id
  public_subnet_ids     = module.networking.public_subnet_ids
  alb_security_group_id = aws_security_group.alb.id
}

# ──────────────────────────────────────────────
#  ECS — Fargate Cluster + Services
# ──────────────────────────────────────────────
module "ecs" {
  source = "./modules/ecs"

  project_name          = var.project_name
  environment           = var.environment
  aws_region            = var.aws_region
  private_subnet_ids    = module.networking.private_subnet_ids
  ecs_security_group_id = aws_security_group.ecs_tasks.id

  execution_role_arn = var.execution_role_arn
  task_role_arn      = var.task_role_arn

  core_api_image         = module.ecr.repository_urls["core-api"]
  routing_service_image  = module.ecr.repository_urls["routing-service"]
  tracking_service_image = module.ecr.repository_urls["tracking-service"]
  order_service_image    = module.ecr.repository_urls["order-service"]

  core_api_target_group_arn = module.alb.core_api_target_group_arn
  routing_target_group_arn  = module.alb.routing_target_group_arn
  tracking_target_group_arn = module.alb.tracking_target_group_arn
  order_target_group_arn    = module.alb.order_target_group_arn

  core_api_alb_resource_label = "${module.alb.arn_suffix}/${module.alb.core_api_target_group_arn_suffix}"
  routing_alb_resource_label  = "${module.alb.arn_suffix}/${module.alb.routing_target_group_arn_suffix}"

  alb_dns_name = module.alb.dns_name

  database_url        = local.database_url
  dynamodb_table_name = module.dynamodb.courier_positions_table_name
  dynamodb_table_arn  = module.dynamodb.courier_positions_table_arn
  graph_bucket_name   = module.s3.graph_bucket_name
  graph_bucket_arn    = module.s3.graph_bucket_arn

  core_api_cpu     = var.core_api_cpu
  core_api_memory  = var.core_api_memory
  core_api_desired = var.core_api_desired
  core_api_min     = var.core_api_min
  core_api_max     = var.core_api_max

  routing_cpu     = var.routing_cpu
  routing_memory  = var.routing_memory
  routing_desired = var.routing_desired
  routing_min     = var.routing_min
  routing_max     = var.routing_max

  tracking_cpu     = var.tracking_cpu
  tracking_memory  = var.tracking_memory
  tracking_desired = var.tracking_desired
  tracking_min     = var.tracking_min
  tracking_max     = var.tracking_max

  order_cpu     = var.order_cpu
  order_memory  = var.order_memory
  order_desired = var.order_desired
  order_min     = var.order_min
  order_max     = var.order_max
}