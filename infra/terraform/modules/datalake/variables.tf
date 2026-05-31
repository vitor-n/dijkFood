variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  description = "Região usada na conversão de formato (schema_configuration do Firehose)."
  type        = string
  default     = "us-east-1"
}

variable "firehose_role_arn" {
  description = "ARN da IAM Role do Learner Lab (LabRole)"
  type        = string
}

variable "firehose_buffer_seconds" {
  description = "Intervalo de buffering do Firehose antes de gravar no S3."
  type        = number
  default     = 60
}

variable "firehose_buffer_mb" {
  description = "Tamanho de buffering do Firehose (MB). Mínimo 64 com conversão p/ Parquet."
  type        = number
  default     = 128
}
