variable "project_name" { type = string }
variable "aws_region" { type = string }
variable "vpc_id" { type = string }
variable "subnet_id" {
  description = "Subnet pública para a EC2 do dashboard"
  type        = string
}
variable "instance_type" {
  type    = string
  default = "t3.small"
}
variable "image" {
  description = "URL do repositório ECR do dashboard-service (sem tag)"
  type        = string
}
variable "glue_database" { type = string }
variable "athena_workgroup" { type = string }
variable "datalake_bucket" { type = string }
variable "assistant_url" {
  description = "URL do assistente (ALB) para o link no dashboard"
  type        = string
  default     = "/chat"
}
