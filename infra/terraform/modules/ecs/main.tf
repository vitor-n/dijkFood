# ──────────────────────────────────────────────
#  ECS Cluster
# ──────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 1
    capacity_provider = "FARGATE"
  }

  default_capacity_provider_strategy {
    weight            = 3
    capacity_provider = "FARGATE_SPOT"
  }
}

# ──────────────────────────────────────────────
#  IAM — Execution Role (pull images, push logs)
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
#  IAM — Task Role (S3, DynamoDB access at runtime)
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
#  CloudWatch Log Groups
# ──────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "core_api" {
  name              = "/ecs/${var.project_name}/core-api"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "routing" {
  name              = "/ecs/${var.project_name}/routing-service"
  retention_in_days = 7
}

# ──────────────────────────────────────────────
#  Task Definitions
# ──────────────────────────────────────────────

resource "aws_ecs_task_definition" "core_api" {
  family                   = "${var.project_name}-core-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.core_api_cpu
  memory                   = var.core_api_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name  = "core-api"
    image = "${var.core_api_image}:latest"

    portMappings = [{ containerPort = 8000, protocol = "tcp" }]

    environment = [
      { name = "POSTGRES_ENDPOINT", value = var.database_url },
      { name = "DATABASE_URL", value = var.database_url },
      { name = "DYNAMO_TABLE", value = var.dynamodb_table_name },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "AWS_DEFAULT_REGION", value = var.aws_region },
      { name = "FIREHOSE_STREAM_NAME", value = var.firehose_stream_name },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.core_api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')\" || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }

    essential = true
  }])
}

resource "aws_ecs_task_definition" "routing" {
  family                   = "${var.project_name}-routing"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.routing_cpu
  memory                   = var.routing_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    # ── Container 1: OSRM backend (C++) ─────────────────────────────────────
    # Baixa os arquivos .osrm pré-processados do S3 no startup, depois sobe
    # o servidor OSRM. O routing-service só sobe após este container passar
    # no healthCheck (condição HEALTHY).
    {
      name       = "osrm-backend"
      image      = "ghcr.io/project-osrm/osrm-backend:v5.27.1"
      entryPoint = ["/bin/sh", "-c"]
      command = [
        "apt-get update -qq && apt-get install -y -qq awscli curl && mkdir -p /data && aws s3 sync s3://${var.graph_bucket_name}/osrm/processed/ /data/ && echo 'Download OSRM concluido' && osrm-routed --algorithm MLD /data/sao_paulo.osrm --port 5000 --max-table-size 10000"
      ]

      environment = [
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
      ]

      portMappings = [{ containerPort = 5000, protocol = "tcp" }]

      mountPoints = [{ sourceVolume = "osrm-data", containerPath = "/data", readOnly = false }]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.routing.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "osrm"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -sf 'http://localhost:5000/route/v1/driving/-46.6388,-23.5489;-46.6588,-23.5689?overview=false' | grep -q '\"code\":\"Ok\"' || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 5
        startPeriod = 180
      }

      essential = true
    },

    # ── Container 2: routing-service FastAPI (proxy leve) ───────────────────
    # Recebe chamadas do ALB na porta 8001 e as repassa ao osrm-backend
    # via localhost:5000. Só sobe após osrm-backend estar HEALTHY.
    {
      name  = "routing-service"
      image = "${var.routing_service_image}:latest"

      portMappings = [{ containerPort = 8001, protocol = "tcp" }]

      environment = [
        { name = "OSRM_URL",           value = "http://localhost:5000" },
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
      ]

      dependsOn = [{ containerName = "osrm-backend", condition = "HEALTHY" }]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.routing.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8001/healthz')\" || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 210
      }

      essential = true
    }
  ])

  volume {
    name = "osrm-data"
    # Volume efêmero compartilhado entre os dois containers da task.
    # O osrm-backend popula /data/ via aws s3 sync no startup.
  }
}

# ──────────────────────────────────────────────
#  ECS Services
# ──────────────────────────────────────────────

resource "aws_ecs_service" "core_api" {
  name                   = "${var.project_name}-core-api"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.core_api.arn
  desired_count          = var.core_api_desired
  launch_type            = "FARGATE"
  enable_execute_command = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.core_api_target_group_arn
    container_name   = "core-api"
    container_port   = 8000
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60

  lifecycle { ignore_changes = [desired_count, task_definition] }

}

resource "aws_ecs_service" "routing" {
  name                   = "${var.project_name}-routing"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.routing.arn
  desired_count          = var.routing_desired
  launch_type            = "FARGATE"
  enable_execute_command = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.routing_target_group_arn
    container_name   = "routing-service"
    container_port   = 8001
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 120

  lifecycle { ignore_changes = [desired_count, task_definition] }
}

# ──────────────────────────────────────────────
#  Auto Scaling — core-api
# ──────────────────────────────────────────────



resource "aws_appautoscaling_target" "core_api" {
  max_capacity       = var.core_api_max
  min_capacity       = var.core_api_min
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.core_api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "core_api_cpu" {
  name               = "${var.project_name}-core-api-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.core_api.resource_id
  scalable_dimension = aws_appautoscaling_target.core_api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.core_api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 60.0
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "core_api_requests" {
  name               = "${var.project_name}-core-api-alb-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.core_api.resource_id
  scalable_dimension = aws_appautoscaling_target.core_api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.core_api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = var.core_api_alb_resource_label
    }
    target_value       = 100
    scale_in_cooldown  = 120
    scale_out_cooldown = 30
  }
}

# ──────────────────────────────────────────────
#  Auto Scaling — routing-service
# ──────────────────────────────────────────────

resource "aws_appautoscaling_target" "routing" {
  max_capacity       = var.routing_max
  min_capacity       = var.routing_min
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.routing.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "routing_cpu" {
  name               = "${var.project_name}-routing-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.routing.resource_id
  scalable_dimension = aws_appautoscaling_target.routing.scalable_dimension
  service_namespace  = aws_appautoscaling_target.routing.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 60
    scale_in_cooldown  = 60
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "routing_requests" {
  name               = "${var.project_name}-routing-alb-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.routing.resource_id
  scalable_dimension = aws_appautoscaling_target.routing.scalable_dimension
  service_namespace  = aws_appautoscaling_target.routing.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = var.routing_alb_resource_label
    }
    target_value       = 10
    scale_in_cooldown  = 60
    scale_out_cooldown = 30
  }
}

resource "aws_cloudwatch_log_group" "tracking" {
  name              = "/ecs/${var.project_name}/tracking-service"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "order" {
  name              = "/ecs/${var.project_name}/order-service"
  retention_in_days = 7
}

resource "aws_ecs_task_definition" "tracking" {
  family                   = "${var.project_name}-tracking"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.tracking_cpu
  memory                   = var.tracking_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name  = "tracking-service"
    image = "${var.tracking_service_image}:latest"

    portMappings = [{ containerPort = 8002, protocol = "tcp" }]

    environment = [
      { name = "DYNAMO_TABLE", value = var.dynamodb_table_name },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "AWS_DEFAULT_REGION", value = var.aws_region },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.tracking.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8002/healthz')\" || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }

    essential = true
  }])
}

resource "aws_ecs_task_definition" "order" {
  family                   = "${var.project_name}-order"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.order_cpu
  memory                   = var.order_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name  = "order-service"
    image = "${var.order_service_image}:latest"

    portMappings = [{ containerPort = 8003, protocol = "tcp" }]

    environment = [
      { name = "POSTGRES_ENDPOINT", value = var.database_url },
      { name = "DATABASE_URL", value = var.database_url },
      { name = "TRACKING_SERVICE_ENDPOINT", value = "http://${var.alb_dns_name}/" },
      { name = "PREDICTION_SERVICE_ENDPOINT", value = var.prediction_service_endpoint },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "AWS_DEFAULT_REGION", value = var.aws_region },
      { name = "FIREHOSE_STREAM_NAME", value = var.firehose_stream_name },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.order.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8003/healthz')\" || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }

    essential = true
  }])
}

resource "aws_ecs_service" "tracking" {
  name                   = "${var.project_name}-tracking"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.tracking.arn
  desired_count          = var.tracking_desired
  launch_type            = "FARGATE"
  enable_execute_command = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.tracking_target_group_arn
    container_name   = "tracking-service"
    container_port   = 8002
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60

  lifecycle { ignore_changes = [desired_count, task_definition] }
}

resource "aws_ecs_service" "order" {
  name                   = "${var.project_name}-order"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.order.arn
  desired_count          = var.order_desired
  launch_type            = "FARGATE"
  enable_execute_command = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.order_target_group_arn
    container_name   = "order-service"
    container_port   = 8003
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60

  lifecycle { ignore_changes = [desired_count, task_definition] }
}

resource "aws_appautoscaling_target" "tracking" {
  max_capacity       = var.tracking_max
  min_capacity       = var.tracking_min
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.tracking.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "tracking_cpu" {
  name               = "${var.project_name}-tracking-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.tracking.resource_id
  scalable_dimension = aws_appautoscaling_target.tracking.scalable_dimension
  service_namespace  = aws_appautoscaling_target.tracking.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 60.0
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "tracking_requests" {
  name               = "${var.project_name}-tracking-alb-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.tracking.resource_id
  scalable_dimension = aws_appautoscaling_target.tracking.scalable_dimension
  service_namespace  = aws_appautoscaling_target.tracking.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = var.tracking_alb_resource_label
    }
    target_value       = 250
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_target" "order" {
  max_capacity       = var.order_max
  min_capacity       = var.order_min
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.order.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "order_cpu" {
  name               = "${var.project_name}-order-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.order.resource_id
  scalable_dimension = aws_appautoscaling_target.order.scalable_dimension
  service_namespace  = aws_appautoscaling_target.order.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 60.0
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "order_requests" {
  name               = "${var.project_name}-order-alb-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.order.resource_id
  scalable_dimension = aws_appautoscaling_target.order.scalable_dimension
  service_namespace  = aws_appautoscaling_target.order.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = var.order_alb_resource_label
    }
    target_value       = 30
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}
