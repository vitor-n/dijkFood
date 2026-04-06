variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "security_group_id" {
  type = string
}

variable "tracking_service_image" {
  description = "ECR repository URL for tracking-service"
  type        = string
}

variable "order_service_image" {
  description = "ECR repository URL for order-service"
  type        = string
}

variable "tracking_target_group_arn" {
  type = string
}

variable "order_target_group_arn" {
  type = string
}

variable "alb_dns_name" {
  type = string
}

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
  default = 1
}

variable "tracking_min" {
  type    = number
  default = 1
}

variable "tracking_max" {
  type    = number
  default = 2
}

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
  default = 1
}

variable "order_min" {
  type    = number
  default = 1
}

variable "order_max" {
  type    = number
  default = 2
}