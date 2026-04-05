output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "cluster_arn" {
  value = aws_ecs_cluster.main.arn
}

output "core_api_service_name" {
  value = aws_ecs_service.core_api.name
}

output "routing_service_name" {
  value = aws_ecs_service.routing.name
}

output "execution_role_arn" {
  value = var.execution_role_arn
}

output "task_role_arn" {
  value = var.task_role_arn
}
