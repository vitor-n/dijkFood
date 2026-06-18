variable "project_name" {
  type = string
}

variable "role_arn" {
  description = "ARN da LabRole (Step Functions, SageMaker, Lambda, Scheduler)"
  type        = string
}

variable "datalake_bucket" {
  description = "Bucket do datalake (artefatos de modelo + previsões)"
  type        = string
}

variable "glue_database" {
  type = string
}

variable "athena_workgroup" {
  type = string
}

variable "prediction_url" {
  description = "Base http do prediction-service (via ALB) para reload/batch"
  type        = string
  default     = ""
}

variable "model_package_group" {
  description = "Nome do SageMaker Model Package Group (Model Registry)"
  type        = string
  default     = ""
}

variable "model_prefix" {
  type    = string
  default = "models/eta"
}

variable "sourcedir_key" {
  description = "Chave S3 do sourcedir.tar.gz com o train_eta.py (upload via deploy.py)"
  type        = string
  default     = "ml/sourcedir.tar.gz"
}

variable "training_image" {
  description = "URI do container sklearn gerenciado do SageMaker (us-east-1)"
  type        = string
  default     = "683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3"
}

variable "training_instance_type" {
  type    = string
  default = "ml.m5.large"
}

variable "train_lookback_days" {
  type    = number
  default = 60
}

variable "schedule_expression" {
  description = "Periodicidade do retreino (EventBridge Scheduler)"
  type        = string
  default     = "rate(1 day)"
}
