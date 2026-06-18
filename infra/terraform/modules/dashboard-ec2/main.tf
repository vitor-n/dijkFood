# ──────────────────────────────────────────────────────────────────────────────
#  dashboard-ec2 — dashboard analítico numa ÚNICA EC2 (sem ECS/autoscaling).
#
#  O dashboard tem tráfego baixo e previsível: não precisa de Fargate nem de
#  escalonamento. Roda o container do dashboard-service numa instância dedicada,
#  acessível diretamente na porta 80. Consulta Athena/S3 via LabInstanceProfile.
# ──────────────────────────────────────────────────────────────────────────────

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

resource "aws_security_group" "dashboard" {
  name_prefix = "${var.project_name}-dashboard-"
  description = "Dashboard EC2 public HTTP"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle { create_before_destroy = true }
  tags = { Name = "${var.project_name}-dashboard-sg" }
}

resource "aws_instance" "dashboard" {
  ami                         = data.aws_ami.amazon_linux.id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.dashboard.id]
  associate_public_ip_address = true
  iam_instance_profile        = "LabInstanceProfile"

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    image         = var.image
    region        = var.aws_region
    glue_db       = var.glue_database
    athena_wg     = var.athena_workgroup
    bucket        = var.datalake_bucket
    assistant_url = var.assistant_url
  })

  user_data_replace_on_change = true

  # hop_limit=2 permite que o container (bridge docker) alcance o IMDSv2 e use
  # as credenciais do instance profile (LabRole) para Athena/S3.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "optional"
    http_put_response_hop_limit = 2
  }

  tags = {
    Name      = "${var.project_name}-dashboard"
    Component = "dashboard"
  }
}
