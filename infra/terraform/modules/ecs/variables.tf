variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

# Networking
variable "private_subnet_ids" {
  type = list(string)
}

variable "ecs_security_group_id" {
  type = string
}

# Images
variable "core_api_image" {
  description = "ECR repository URL for core-api"
  type        = string
}

variable "routing_service_image" {
  description = "ECR repository URL for routing-service"
  type        = string
}

variable "tracking_service_image" {
  description = "ECR repository URL for tracking-service"
  type        = string
}

variable "order_service_image" {
  description = "ECR repository URL for order-service"
  type        = string
}

# Load Balancer
variable "core_api_target_group_arn" {
  type = string
}

variable "routing_target_group_arn" {
  type = string
}

variable "tracking_target_group_arn" {
  type = string
}

variable "order_target_group_arn" {
  type = string
}

variable "core_api_alb_resource_label" {
  description = "ALB resource label for core-api auto-scaling (arn_suffix/tg_arn_suffix)"
  type        = string
}

variable "routing_alb_resource_label" {
  description = "ALB resource label for routing auto-scaling (arn_suffix/tg_arn_suffix)"
  type        = string
}

variable "alb_dns_name" {
  type = string
}

# Service configuration
variable "database_url" {
  type      = string
  sensitive = true
}

variable "dynamodb_table_name" {
  type = string
}

variable "dynamodb_table_arn" {
  type = string
}

variable "graph_bucket_name" {
  type = string
}

variable "graph_bucket_arn" {
  type = string
}

# core-api sizing
variable "core_api_cpu" {
  type    = number
  default = 2048
}

variable "core_api_memory" {
  type    = number
  default = 4096
}

variable "core_api_desired" {
  type    = number
  default = 2
}

variable "core_api_min" {
  type    = number
  default = 2
}

variable "core_api_max" {
  type    = number
  default = 12
}

# routing-service sizing
variable "routing_cpu" {
  type    = number
  default = 1024
}

variable "routing_memory" {
  type    = number
  default = 2048
}

variable "routing_desired" {
  type    = number
  default = 6
}

variable "routing_min" {
  type    = number
  default = 6
}

variable "routing_max" {
  type    = number
  default = 12
}

# tracking-service sizing
variable "tracking_cpu" {
  type    = number
  default = 512
}

variable "tracking_memory" {
  type    = number
  default = 1024
}

variable "tracking_desired" {
  type    = number
  default = 2
}

variable "tracking_min" {
  type    = number
  default = 2
}

variable "tracking_max" {
  type    = number
  default = 4
}

# order-service sizing
variable "order_cpu" {
  type    = number
  default = 512
}

variable "order_memory" {
  type    = number
  default = 1024
}

variable "order_desired" {
  type    = number
  default = 4
}

variable "order_min" {
  type    = number
  default = 4
}

variable "order_max" {
  type    = number
  default = 8
}

variable "execution_role_arn" {
  description = "Existing IAM role ARN for ECS task execution"
  type        = string
}

variable "task_role_arn" {
  description = "Existing IAM role ARN for ECS application task"
  type        = string
}