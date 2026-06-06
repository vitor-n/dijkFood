locals {
  services = [
    "core-api",
    "routing-service",
    "tracking-service",
    "order-service",
    # Camada analítica / Objetivo 3
    "dashboard-service",
    "prediction-service",
    "assistant-service",
  ]
  database_url = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${module.rds.endpoint}:5432/dijkfood"

  alb_base_url = "http://${module.alb.dns_name}"

  # Ambiente comum aos serviços que consultam a camada analítica (Athena/Glue)
  analytics_env = [
    { name = "AWS_REGION", value = var.aws_region },
    { name = "AWS_DEFAULT_REGION", value = var.aws_region },
    { name = "GLUE_DATABASE", value = module.datalake.glue_database_name },
    { name = "ATHENA_WORKGROUP", value = module.datalake.athena_workgroup_name },
    { name = "DATALAKE_BUCKET", value = module.datalake.datalake_bucket_name },
  ]
}

data "aws_iam_role" "lab_role" {
  name = "LabRole"
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
    to_port         = 8006
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
  description = "Allow PostgreSQL from ECS tasks, Lambda, and VPC"
  vpc_id      = module.networking.vpc_id

  ingress {
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  ingress {
    description     = "outbox-publisher Lambda"
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [aws_security_group.lambda.id]
  }

  ingress {
    description = "Allow PostgreSQL from within VPC"
    protocol    = "tcp"
    from_port   = 5432
    to_port     = 5432
    cidr_blocks = [var.vpc_cidr]
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

# SG da Lambda outbox-publisher (na VPC, alcança RDS + egress p/ Firehose via NAT)
resource "aws_security_group" "lambda" {
  name_prefix = "${var.project_name}-lambda-"
  description = "Outbox-publisher Lambda egress"
  vpc_id      = module.networking.vpc_id

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle { create_before_destroy = true }
  tags = { Name = "${var.project_name}-lambda-sg" }
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
#  Datalake (S3 + Firehose)
# ──────────────────────────────────────────────
module "datalake" {
  source = "./modules/datalake"

  project_name = var.project_name
  environment  = var.environment

  firehose_role_arn = data.aws_iam_role.lab_role.arn
  glue_role_arn     = data.aws_iam_role.lab_role.arn
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

  execution_role_arn = data.aws_iam_role.lab_role.arn
  task_role_arn      = data.aws_iam_role.lab_role.arn

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
  tracking_alb_resource_label = "${module.alb.arn_suffix}/${module.alb.tracking_target_group_arn_suffix}"
  order_alb_resource_label    = "${module.alb.arn_suffix}/${module.alb.order_target_group_arn_suffix}"

  alb_dns_name = module.alb.dns_name

  database_url        = local.database_url
  dynamodb_table_name = module.dynamodb.courier_positions_table_name
  dynamodb_table_arn  = module.dynamodb.courier_positions_table_arn
  graph_bucket_name   = module.s3.graph_bucket_name
  graph_bucket_arn    = module.s3.graph_bucket_arn

  firehose_stream_name        = module.datalake.firehose_stream_name
  prediction_service_endpoint = "${local.alb_base_url}/"

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


# ──────────────────────────────────────────────
#  Lambda — position-forwarder (DynamoDB Streams → Firehose)
# ──────────────────────────────────────────────
module "position_forwarder" {
  source = "./modules/lambda"

  project_name         = var.project_name
  lambda_role_arn      = data.aws_iam_role.lab_role.arn
  firehose_stream_name = module.datalake.firehose_stream_name
  dynamodb_stream_arn  = module.dynamodb.courier_positions_stream_arn

  # outbox-publisher (VPC → RDS → Firehose)
  vpc_subnet_ids           = module.networking.private_subnet_ids
  lambda_security_group_id = aws_security_group.lambda.id
  db_host                  = module.rds.endpoint
  db_name                  = "dijkfood"
  db_user                  = var.db_username
  db_password              = var.db_password
}

# ──────────────────────────────────────────────
#  Serviços analíticos (ECS) — Objetivo 3
# ──────────────────────────────────────────────
module "dashboard_service" {
  source = "./modules/app-service"

  project_name = var.project_name
  name         = "dashboard-service"
  aws_region   = var.aws_region
  image        = module.ecr.repository_urls["dashboard-service"]

  container_port = 8004
  cpu            = var.dashboard_cpu
  memory         = var.dashboard_memory
  desired_count  = var.dashboard_desired
  min_count      = var.dashboard_min
  max_count      = var.dashboard_max

  environment = local.analytics_env

  cluster_id            = module.ecs.cluster_id
  cluster_name          = module.ecs.cluster_name
  execution_role_arn    = data.aws_iam_role.lab_role.arn
  task_role_arn         = data.aws_iam_role.lab_role.arn
  private_subnet_ids    = module.networking.private_subnet_ids
  ecs_security_group_id = aws_security_group.ecs_tasks.id
  vpc_id                = module.networking.vpc_id

  listener_arn           = module.alb.http_listener_arn
  listener_rule_priority = 130
  path_patterns          = ["/dashboard", "/dashboard/*"]
}

module "prediction_service" {
  source = "./modules/app-service"

  project_name = var.project_name
  name         = "prediction-service"
  aws_region   = var.aws_region
  image        = module.ecr.repository_urls["prediction-service"]

  container_port = 8005
  cpu            = var.prediction_cpu
  memory         = var.prediction_memory
  desired_count  = var.prediction_desired
  min_count      = var.prediction_min
  max_count      = var.prediction_max

  environment = concat(local.analytics_env, [
    { name = "SNS_TOPIC_ARN", value = aws_sns_topic.alerts.arn },
  ])

  cluster_id            = module.ecs.cluster_id
  cluster_name          = module.ecs.cluster_name
  execution_role_arn    = data.aws_iam_role.lab_role.arn
  task_role_arn         = data.aws_iam_role.lab_role.arn
  private_subnet_ids    = module.networking.private_subnet_ids
  ecs_security_group_id = aws_security_group.ecs_tasks.id
  vpc_id                = module.networking.vpc_id

  listener_arn           = module.alb.http_listener_arn
  listener_rule_priority = 140
  path_patterns          = ["/predict", "/predict/*", "/train/*", "/batch/*", "/model/*"]
}

module "assistant_service" {
  source = "./modules/app-service"

  project_name = var.project_name
  name         = "assistant-service"
  aws_region   = var.aws_region
  image        = module.ecr.repository_urls["assistant-service"]

  container_port = 8006
  cpu            = var.assistant_cpu
  memory         = var.assistant_memory
  desired_count  = var.assistant_desired
  min_count      = var.assistant_min
  max_count      = var.assistant_max

  environment = concat(local.analytics_env, [
    { name = "USE_BEDROCK", value = tostring(var.assistant_use_bedrock) },
    { name = "BEDROCK_REGION", value = var.bedrock_region },
    { name = "BEDROCK_MODEL_ID", value = var.bedrock_model_id },
    { name = "BEDROCK_AWS_ACCESS_KEY_ID", value = var.bedrock_aws_access_key_id },
    { name = "BEDROCK_AWS_SECRET_ACCESS_KEY", value = var.bedrock_aws_secret_access_key },
  ])

  cluster_id            = module.ecs.cluster_id
  cluster_name          = module.ecs.cluster_name
  execution_role_arn    = data.aws_iam_role.lab_role.arn
  task_role_arn         = data.aws_iam_role.lab_role.arn
  private_subnet_ids    = module.networking.private_subnet_ids
  ecs_security_group_id = aws_security_group.ecs_tasks.id
  vpc_id                = module.networking.vpc_id

  listener_arn           = module.alb.http_listener_arn
  listener_rule_priority = 150
  path_patterns          = ["/chat", "/chat/*"]
}

# ──────────────────────────────────────────────
#  Pipeline gerenciada de retreino (SageMaker + Step Functions + EventBridge)
# ──────────────────────────────────────────────
module "ml_pipeline" {
  source = "./modules/ml"

  project_name        = var.project_name
  role_arn            = data.aws_iam_role.lab_role.arn
  datalake_bucket     = module.datalake.datalake_bucket_name
  glue_database       = module.datalake.glue_database_name
  athena_workgroup    = module.datalake.athena_workgroup_name
  prediction_url      = local.alb_base_url
  model_package_group = aws_sagemaker_model_package_group.eta.model_package_group_name

  schedule_expression = var.ml_retrain_schedule
}

# ──────────────────────────────────────────────
#  Alertas — SNS + CloudWatch alarms
# ──────────────────────────────────────────────
resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "outbox_errors" {
  alarm_name          = "${var.project_name}-outbox-publisher-errors"
  alarm_description   = "Erros no relay do outbox transacional — risco de perda/atraso de eventos analíticos."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions    = { FunctionName = module.position_forwarder.outbox_publisher_name }
  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "position_forwarder_errors" {
  alarm_name          = "${var.project_name}-position-forwarder-errors"
  alarm_description   = "Erros no CDC de posições (DynamoDB Streams → Firehose)."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions    = { FunctionName = module.position_forwarder.function_name }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# SageMaker Model Registry — versionamento dos modelos de ETA
resource "aws_sagemaker_model_package_group" "eta" {
  model_package_group_name        = "${var.project_name}-eta"
  model_package_group_description = "Versões aprovadas do modelo de predição de ETA"
}

# ──────────────────────────────────
#  EC2 - Will host the load tester
# ──────────────────────────────────

module "load_tester" {
  source        = "./modules/ec2"
  vpc_id        = module.networking.vpc_id
  subnet_id     = module.networking.public_subnet_ids[0]
  instance_type = var.load_tester_instance_type
  alb_dns       = module.alb.dns_name
}
