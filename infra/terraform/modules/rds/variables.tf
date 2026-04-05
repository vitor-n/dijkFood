variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "database_subnet_ids" {
  type = list(string)
}

variable "security_group_id" {
  type = string
}

variable "db_username" {
  type      = string
  sensitive = true
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "multi_az" {
  type    = bool
  default = true
}
