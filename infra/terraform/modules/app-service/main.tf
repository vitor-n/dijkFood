# ──────────────────────────────────────────────────────────────────────────────
#  app-service — módulo genérico para os serviços analíticos no ECS/Fargate
#  (task def + service + autoscaling + target group + regra de listener no ALB).
#  Mantém os módulos originais (ecs/alb) intocados, reduzindo risco de regressão.
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.project_name}/${var.name}"
  retention_in_days = 7
}

resource "aws_lb_target_group" "this" {
  name        = "${var.project_name}-${replace(var.name, "-service", "")}"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = var.health_check_path
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30
  tags                 = { Service = var.name }
}

resource "aws_lb_listener_rule" "this" {
  listener_arn = var.listener_arn
  priority     = var.listener_rule_priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }

  condition {
    path_pattern { values = var.path_patterns }
  }
}

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.project_name}-${var.name}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name         = var.name
    image        = "${var.image}:latest"
    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]
    environment  = var.environment

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.this.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:${var.container_port}${var.health_check_path}')\" || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 90
    }

    essential = true
  }])
}

resource "aws_ecs_service" "this" {
  name                   = "${var.project_name}-${var.name}"
  cluster                = var.cluster_id
  task_definition        = aws_ecs_task_definition.this.arn
  desired_count          = var.desired_count
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
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = var.name
    container_port   = var.container_port
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 90

  lifecycle { ignore_changes = [desired_count, task_definition] }
}

resource "aws_appautoscaling_target" "this" {
  max_capacity       = var.max_count
  min_capacity       = var.min_count
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.this.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${var.project_name}-${var.name}-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.this.resource_id
  scalable_dimension = aws_appautoscaling_target.this.scalable_dimension
  service_namespace  = aws_appautoscaling_target.this.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = var.cpu_target
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}
