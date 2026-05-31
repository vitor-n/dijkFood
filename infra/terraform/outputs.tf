output "aws_region" {
  description = "AWS region"
  value       = var.aws_region
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.networking.vpc_id
}

output "alb_dns_name" {
  description = "ALB DNS name — main entry-point for the API"
  value       = module.alb.dns_name
}

output "ecr_repository_urls" {
  description = "ECR repository URLs per service"
  value       = module.ecr.repository_urls
}

output "rds_endpoint" {
  description = "RDS writer endpoint"
  value       = module.rds.endpoint
  sensitive   = true
}

output "graph_bucket_name" {
  description = "S3 bucket for graph data"
  value       = module.s3.graph_bucket_name
}

output "dynamodb_table_name" {
  description = "DynamoDB table for courier tracking"
  value       = module.dynamodb.courier_positions_table_name
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "core_api_service_name" {
  description = "ECS service name for core-api"
  value       = module.ecs.core_api_service_name
}

output "routing_service_name" {
  description = "ECS service name for routing-service"
  value       = module.ecs.routing_service_name
}

output "tracking_service_name" {
  description = "ECS service name for tracking-service"
  value       = module.ecs.tracking_service_name
}

output "order_service_name" {
  description = "ECS service name for order-service"
  value       = module.ecs.order_service_name
}

output "dashboard_service_name" {
  description = "ECS service name for dashboard-service"
  value       = module.ecs.dashboard_service_name
}

output "prediction_service_name" {
  description = "ECS service name for prediction-service"
  value       = module.ecs.prediction_service_name
}

output "dashboard_url" {
  description = "URL do dashboard analítico (Objetivo 3)"
  value       = "http://${module.alb.dns_name}/dashboard"
}

output "load_tester_instance_id" {
  description = "ID da EC2 responsável pelo teste de carga"
  value       = module.load_tester.instance_id
}

# ---------- Analytics layer (Objetivo 3) ----------

output "firehose_stream_name" {
  description = "Firehose (DirectPut) que entrega eventos em Parquet no datalake"
  value       = module.datalake.firehose_stream_name
}

output "datalake_bucket_name" {
  description = "Bucket S3 do data lake analítico"
  value       = module.datalake.datalake_bucket_name
}

output "glue_database_name" {
  description = "Glue Data Catalog database"
  value       = module.datalake.glue_database_name
}

output "athena_workgroup_name" {
  description = "Athena workgroup para consultas analíticas"
  value       = module.datalake.athena_workgroup_name
}

output "position_forwarder_function_name" {
  description = "Lambda que faz CDC do DynamoDB Streams para o Firehose"
  value       = module.analytics_lambdas.position_forwarder_function_name
}

