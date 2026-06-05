variable "project_name" { type = string }
variable "name" {
  description = "Nome curto do serviço (ex.: dashboard-service)"
  type        = string
}
variable "aws_region" { type = string }

variable "image" {
  description = "URL do repositório ECR (sem tag)"
  type        = string
}
variable "container_port" { type = number }

variable "cpu" { type = number }
variable "memory" { type = number }
variable "desired_count" { type = number }
variable "min_count" { type = number }
variable "max_count" { type = number }

variable "environment" {
  description = "Variáveis de ambiente do container"
  type        = list(object({ name = string, value = string }))
  default     = []
}

# Infra compartilhada
variable "cluster_id" { type = string }
variable "cluster_name" { type = string }
variable "execution_role_arn" { type = string }
variable "task_role_arn" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "ecs_security_group_id" { type = string }
variable "vpc_id" { type = string }

# Roteamento no ALB
variable "listener_arn" { type = string }
variable "listener_rule_priority" { type = number }
variable "path_patterns" {
  description = "Padrões de path roteados para este serviço"
  type        = list(string)
}
variable "health_check_path" {
  type    = string
  default = "/healthz"
}

variable "cpu_target" {
  type    = number
  default = 60
}
