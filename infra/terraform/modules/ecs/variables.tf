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

variable "dashboard_service_image" {
  description = "ECR repository URL for dashboard-service"
  type        = string
}

variable "prediction_service_image" {
  description = "ECR repository URL for prediction-service"
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

variable "dashboard_target_group_arn" {
  type = string
}

variable "prediction_target_group_arn" {
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

variable "tracking_alb_resource_label" {
  description = "ALB resource label for tracking auto-scaling (arn_suffix/tg_arn_suffix)"
  type        = string
}

variable "order_alb_resource_label" {
  description = "ALB resource label for order auto-scaling (arn_suffix/tg_arn_suffix)"
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
  type = number
}

variable "core_api_memory" {
  type = number
}

variable "core_api_desired" {
  type = number
}

variable "core_api_min" {
  type = number
}

variable "core_api_max" {
  type = number
}

# routing-service sizing
variable "routing_cpu" {
  type = number
}

variable "routing_memory" {
  type = number
}

variable "routing_desired" {
  type = number
}

variable "routing_min" {
  type = number
}

variable "routing_max" {
  type = number
}

# tracking-service sizing
variable "tracking_cpu" {
  type = number
}

variable "tracking_memory" {
  type = number
}

variable "tracking_desired" {
  type = number
}

variable "tracking_min" {
  type = number
}

variable "tracking_max" {
  type = number
}

# order-service sizing
variable "order_cpu" {
  type = number
}

variable "order_memory" {
  type = number
}

variable "order_desired" {
  type = number
}

variable "order_min" {
  type = number
}

variable "order_max" {
  type = number
}

# dashboard-service sizing
variable "dashboard_cpu" {
  type    = number
  default = 512
}

variable "dashboard_memory" {
  type    = number
  default = 1024
}

variable "dashboard_desired" {
  type    = number
  default = 1
}

variable "dashboard_min" {
  type    = number
  default = 1
}

variable "dashboard_max" {
  type    = number
  default = 4
}

# prediction-service sizing
variable "prediction_cpu" {
  type    = number
  default = 1024
}

variable "prediction_memory" {
  type    = number
  default = 2048
}

variable "prediction_desired" {
  type    = number
  default = 1
}

variable "prediction_min" {
  type    = number
  default = 1
}

# Mantido em 1: o modelo é estado em memória por réplica (ver variables.tf raiz).
variable "prediction_max" {
  type    = number
  default = 1
}

variable "execution_role_arn" {
  description = "Existing IAM role ARN for ECS task execution"
  type        = string
}

variable "task_role_arn" {
  description = "Existing IAM role ARN for ECS application task"
  type        = string
}

variable "athena_workgroup" {
  description = "Athena workgroup usado pelo dashboard."
  type        = string
  default     = ""
}

variable "glue_database" {
  description = "Glue database com a tabela de eventos."
  type        = string
  default     = ""
}

variable "model_bucket" {
  description = "Bucket S3 onde o prediction-service persiste o modelo."
  type        = string
  default     = ""
}

variable "firehose_stream_name" {
  description = "Nome do stream do Firehose para os serviços publicarem eventos"
  type        = string
}
