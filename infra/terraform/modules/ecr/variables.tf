variable "project_name" {
  type = string
}

variable "services" {
  description = "List of service names to create ECR repos for"
  type        = list(string)
}
