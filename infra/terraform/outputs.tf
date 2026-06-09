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

output "load_tester_instance_id" {
  description = "ID da EC2 responsável pelo teste de carga"
  value       = module.load_tester.instance_id
}

# ──────────────────────────────────────────────
#  Camada analítica / Objetivo 3
# ──────────────────────────────────────────────

output "datalake_bucket_name" {
  description = "Bucket S3 do datalake (Firehose, modelos, previsões, catálogo semântico)"
  value       = module.datalake.datalake_bucket_name
}

output "glue_database_name" {
  description = "Database do Glue Data Catalog"
  value       = module.datalake.glue_database_name
}

output "athena_workgroup_name" {
  description = "Workgroup do Athena"
  value       = module.datalake.athena_workgroup_name
}

output "dashboard_instance_id" {
  description = "ID da EC2 que hospeda o dashboard"
  value       = module.dashboard_ec2.instance_id
}

output "prediction_service_name" {
  value = module.prediction_service.service_name
}

output "assistant_service_name" {
  value = module.assistant_service.service_name
}

output "dashboard_url" {
  description = "URL do dashboard analítico (EC2 dedicada)"
  value       = module.dashboard_ec2.url
}

output "assistant_url" {
  description = "URL do assistente conversacional"
  value       = "${module.alb.dns_name}/chat"
}

output "ml_state_machine_arn" {
  description = "Step Functions de retreino do ETA"
  value       = module.ml_pipeline.state_machine_arn
}

output "position_forwarder_lambda" {
  description = "Lambda de CDC das posições (DynamoDB Streams → Firehose)"
  value       = module.position_forwarder.function_name
}

output "outbox_publisher_lambda" {
  description = "Lambda relay do outbox transacional (RDS → Firehose)"
  value       = module.position_forwarder.outbox_publisher_name
}

