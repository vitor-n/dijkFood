data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

resource "aws_security_group" "assistant" {
  name_prefix = "${var.project_name}-assistant-"
  description = "Assistant EC2 SG"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP from ALB/VPC"
    from_port   = 8006
    to_port     = 8006
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # Liberado para simplificar, mas ideal seria restringir ao ALB
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle { create_before_destroy = true }
  tags = { Name = "${var.project_name}-assistant-sg" }
}

resource "aws_instance" "assistant" {
  ami                         = data.aws_ami.amazon_linux.id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.assistant.id]
  associate_public_ip_address = true
  iam_instance_profile        = "LabInstanceProfile"

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    image              = var.image
    region             = var.aws_region
    glue_db            = var.glue_database
    athena_wg          = var.athena_workgroup
    bucket             = var.datalake_bucket
    use_bedrock        = tostring(var.use_bedrock)
    bedrock_region     = var.bedrock_region
    bedrock_model_id   = var.bedrock_model_id
    bedrock_access_key = var.bedrock_access_key
    bedrock_secret_key = var.bedrock_secret_key
  })

  user_data_replace_on_change = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "optional"
    http_put_response_hop_limit = 2
  }

  tags = {
    Name      = "${var.project_name}-assistant"
    Component = "assistant"
  }
}

resource "aws_lb_target_group" "assistant" {
  name        = "${var.project_name}-assistant-ec2"
  port        = 8006
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "instance"

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
  tags                 = { Service = "assistant-service" }
}

resource "aws_lb_target_group_attachment" "assistant" {
  target_group_arn = aws_lb_target_group.assistant.arn
  target_id        = aws_instance.assistant.id
  port             = 8006
}

resource "aws_lb_listener_rule" "assistant" {
  listener_arn = var.listener_arn
  priority     = 150

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.assistant.arn
  }

  condition {
    path_pattern { values = ["/chat", "/chat/*"] }
  }
}
