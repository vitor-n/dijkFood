variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "firehose_role_arn" {
  description = "ARN da IAM Role do Learner Lab (LabRole)"
  type        = string
}

variable "glue_role_arn" {
  description = "ARN da role usada pelo Glue Job (LabRole)"
  type        = string
  default     = ""
}

variable "etl_schedule" {
  description = "Cron do Glue trigger que materializa curated/marts"
  type        = string
  default     = "cron(0 * * * ? *)" # de hora em hora
}
