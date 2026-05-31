variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "production"
}

variable "project_name" {
  description = "Project name used as resource prefix"
  type        = string
  default     = "dijkfood"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "AZs for multi-AZ deployment"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

# ---------- Database ----------

variable "db_username" {
  description = "RDS PostgreSQL master username"
  type        = string
  sensitive   = true
}

variable "db_password" {
  description = "RDS PostgreSQL master password"
  type        = string
  sensitive   = true
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium"
}

variable "db_multi_az" {
  description = "Enable Multi-AZ for RDS"
  type        = bool
  default     = true
}

# ---------- EC2 ----------
variable "load_tester_instance_type" {
  description = "EC2 instance type to load testing"
  type        = string
  default     = "t3.small"
}

# ---------- ECS ----------

variable "core_api_cpu" {
  description = "CPU units for core-api task (1024 = 1 vCPU)"
  type        = number
  default     = 2048
}

variable "core_api_memory" {
  description = "Memory (MiB) for core-api task"
  type        = number
  default     = 4096
}

variable "core_api_desired" {
  description = "Desired task count for core-api"
  type        = number
  default     = 2
}

variable "core_api_min" {
  description = "Min task count for core-api auto-scaling"
  type        = number
  default     = 2
}

variable "core_api_max" {
  description = "Max task count for core-api auto-scaling"
  type        = number
  default     = 12
}

variable "routing_cpu" {
  description = "CPU units for routing-service task"
  type        = number
  default     = 2048
}

variable "routing_memory" {
  description = "Memory (MiB) for routing-service task"
  type        = number
  default     = 4096
}

variable "routing_desired" {
  description = "Desired task count for routing-service"
  type        = number
  default     = 6
}

variable "routing_min" {
  description = "Min task count for routing-service auto-scaling"
  type        = number
  default     = 6
}

variable "routing_max" {
  description = "Max task count for routing-service auto-scaling"
  type        = number
  default     = 60
}

variable "tracking_cpu" {
  description = "CPU units for tracking-service task"
  type        = number
  default     = 512
}

variable "tracking_memory" {
  description = "Memory (MiB) for tracking-service task"
  type        = number
  default     = 1024
}

variable "tracking_desired" {
  description = "Desired task count for tracking-service"
  type        = number
  default     = 2
}

variable "tracking_min" {
  description = "Min task count for tracking-service auto-scaling"
  type        = number
  default     = 2
}

variable "tracking_max" {
  description = "Max task count for tracking-service auto-scaling"
  type        = number
  default     = 60
}

variable "order_cpu" {
  description = "CPU units for order-service task"
  type        = number
  default     = 512
}

variable "order_memory" {
  description = "Memory (MiB) for order-service task"
  type        = number
  default     = 1024
}

variable "order_desired" {
  description = "Desired task count for order-service"
  type        = number
  default     = 4
}

variable "order_min" {
  description = "Min task count for order-service auto-scaling"
  type        = number
  default     = 4
}

variable "order_max" {
  description = "Max task count for order-service auto-scaling"
  type        = number
  default     = 60
}
