output "dns_name" {
  description = "ALB public DNS name"
  value       = aws_lb.main.dns_name
}

output "arn" {
  value = aws_lb.main.arn
}

output "arn_suffix" {
  value = aws_lb.main.arn_suffix
}

output "http_listener_arn" {
  description = "ARN do listener HTTP (para regras de roteamento adicionais)"
  value       = aws_lb_listener.http.arn
}

output "core_api_target_group_arn" {
  value = aws_lb_target_group.core_api.arn
}

output "core_api_target_group_arn_suffix" {
  value = aws_lb_target_group.core_api.arn_suffix
}

output "routing_target_group_arn" {
  value = aws_lb_target_group.routing.arn
}

output "routing_target_group_arn_suffix" {
  value = aws_lb_target_group.routing.arn_suffix
}

output "security_group_id" {
  value = var.alb_security_group_id
}

output "tracking_target_group_arn" {
  value = aws_lb_target_group.tracking.arn
}

output "tracking_target_group_arn_suffix" {
  value = aws_lb_target_group.tracking.arn_suffix
}

output "order_target_group_arn" {
  value = aws_lb_target_group.order.arn
}

output "order_target_group_arn_suffix" {
  value = aws_lb_target_group.order.arn_suffix
}