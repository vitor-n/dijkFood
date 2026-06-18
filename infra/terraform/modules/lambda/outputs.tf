output "pipe_name" {
  value = aws_pipes_pipe.position_forwarder.name
}

output "outbox_publisher_name" {
  value = aws_lambda_function.outbox_publisher.function_name
}

output "outbox_publisher_arn" {
  value = aws_lambda_function.outbox_publisher.arn
}
