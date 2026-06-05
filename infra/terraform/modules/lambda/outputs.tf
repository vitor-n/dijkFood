output "function_name" {
  value = aws_lambda_function.position_forwarder.function_name
}

output "function_arn" {
  value = aws_lambda_function.position_forwarder.arn
}

output "outbox_publisher_name" {
  value = aws_lambda_function.outbox_publisher.function_name
}

output "outbox_publisher_arn" {
  value = aws_lambda_function.outbox_publisher.arn
}
