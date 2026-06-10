variable "project_name" {
  type = string
}

variable "lambda_role_arn" {
  description = "ARN da LabRole (única role disponível no Learner Lab)"
  type        = string
}

variable "firehose_stream_name" {
  description = "Delivery stream do Firehose de destino"
  type        = string
}

variable "firehose_stream_arn" {
  description = "ARN do Delivery stream do Firehose de destino (usado pelo Pipe)"
  type        = string
}

variable "dynamodb_stream_arn" {
  description = "ARN do DynamoDB Stream da tabela de posições"
  type        = string
}

# ── outbox-publisher (VPC + RDS) ──
variable "vpc_subnet_ids" {
  description = "Subnets privadas para a Lambda alcançar o RDS"
  type        = list(string)
}

variable "lambda_security_group_id" {
  description = "Security group da Lambda (permitido pelo SG do RDS)"
  type        = string
}

variable "db_host" {
  type = string
}

variable "db_name" {
  type    = string
  default = "dijkfood"
}

variable "db_user" {
  type      = string
  sensitive = true
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "outbox_schedule" {
  description = "Periodicidade do relay do outbox"
  type        = string
  default     = "rate(1 minute)"
}
