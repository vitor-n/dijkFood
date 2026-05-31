variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "lab_role_arn" {
  description = "Pre-existing IAM role (LabRole) assumed by the Lambda. Learner Lab forbids creating new roles."
  type        = string
}

variable "dynamodb_stream_arn" {
  description = "CourierTracking DynamoDB Streams ARN (CDC source)."
  type        = string
}

variable "firehose_stream_name" {
  description = "Target Firehose delivery stream the forwarder writes courier_position events to."
  type        = string
}

variable "city" {
  type    = string
  default = "sao_paulo"
}
