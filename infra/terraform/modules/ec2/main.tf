data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

resource "aws_security_group" "load_tester" {
  name_prefix = "dijkfood-load-tester-sg-"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "main" {
  ami                    = data.aws_ami.amazon_linux.id
  

  instance_type          = var.instance_type 
  
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.load_tester.id]
  
  iam_instance_profile   = "LabInstanceProfile"

  user_data = <<-EOF
    #!/bin/bash
    cat <<EOT >> /etc/environment
    CRUD_URL="http://${var.alb_dns}"
    ORDER_URL="http://${var.alb_dns}"
    TRACKING_URL="http://${var.alb_dns}"
    ROUTE_URL="http://${var.alb_dns}"
    EOT
  EOF

  tags = {
    Name      = "dijkfood-load-tester"
    Component = "simulation"
  }
}
