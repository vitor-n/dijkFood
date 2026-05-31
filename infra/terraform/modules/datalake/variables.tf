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
