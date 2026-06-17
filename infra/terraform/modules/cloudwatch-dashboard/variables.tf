variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "ecs_cluster_name" {
  type = string
}

variable "core_api_service_name" { type = string }
variable "routing_service_name" { type = string }
variable "tracking_service_name" { type = string }
variable "order_service_name" { type = string }
variable "prediction_service_name" { type = string }

variable "alb_arn_suffix" { type = string }
variable "core_api_tg_suffix" { type = string }
variable "routing_tg_suffix" { type = string }
variable "tracking_tg_suffix" { type = string }
variable "order_tg_suffix" { type = string }
variable "prediction_tg_suffix" { type = string }

variable "dynamodb_table_name" { type = string }
variable "rds_instance_id" { type = string }

variable "ec2_load_tester_id" { type = string }
variable "ec2_dashboard_id" { type = string }
variable "ec2_assistant_id" { type = string }

variable "firehose_stream_name" { type = string }
variable "lambda_outbox_name" { type = string }
