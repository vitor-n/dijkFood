resource "aws_lb" "main" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups = [var.alb_security_group_id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = false

  tags = { Name = "${var.project_name}-alb" }
}

# ── Listener ──

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.core_api.arn
  }
}

# ── Target Groups ──

resource "aws_lb_target_group" "core_api" {
  name        = "${var.project_name}-core-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/healthz"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30
  tags                 = { Service = "core-api" }
}

resource "aws_lb_target_group" "order" {
  name        = "${var.project_name}-order"
  port        = 8003
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/healthz"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30
  tags                 = { Service = "order-service" }
}

resource "aws_lb_target_group" "tracking" {
  name        = "${var.project_name}-tracking"
  port        = 8002
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/healthz"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30
  tags                 = { Service = "tracking-service" }
}

resource "aws_lb_target_group" "routing" {
  name        = "${var.project_name}-routing"
  port        = 8001
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/healthz"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30
  tags                 = { Service = "routing-service" }
}

resource "aws_lb_listener_rule" "tracking_service" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 110

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.tracking.arn
  }

  condition {
    path_pattern { values = ["/tracking/*"] }
  }
}

resource "aws_lb_listener_rule" "order_service" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 120

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.order.arn
  }

  condition {
    path_pattern { values = ["/order", "/order/*"] }
  }
}

# ── Path-based routing rules ──

resource "aws_lb_listener_rule" "routing_service" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.routing.arn
  }

  condition {
    path_pattern { values = ["/routes/*"] }
  }
}
