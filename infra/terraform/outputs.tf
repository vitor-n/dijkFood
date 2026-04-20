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

