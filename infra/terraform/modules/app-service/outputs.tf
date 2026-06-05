output "service_name" {
  value = aws_ecs_service.this.name
}

output "target_group_arn" {
  value = aws_lb_target_group.this.arn
}
