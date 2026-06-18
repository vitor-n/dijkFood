variable "project_name" { type = string }
variable "aws_region" { type = string }
variable "vpc_id" { type = string }
variable "subnet_id" {
  description = "Subnet pública para a EC2 do assistant"
  type        = string
}
variable "instance_type" {
  type    = string
  default = "t3.micro"
}
variable "image" {
  description = "URL do repositório ECR do assistant-service (sem tag)"
  type        = string
}

variable "glue_database" { type = string }
variable "athena_workgroup" { type = string }
variable "datalake_bucket" { type = string }

variable "use_bedrock" { type = bool }
variable "bedrock_region" { type = string }
variable "bedrock_model_id" { type = string }
variable "bedrock_access_key" { type = string }
variable "bedrock_secret_key" { type = string }

variable "listener_arn" { type = string }
