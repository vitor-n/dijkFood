output "courier_positions_table_name" {
  value = aws_dynamodb_table.courier_positions.name
}

output "courier_positions_table_arn" {
  value = aws_dynamodb_table.courier_positions.arn
}

output "courier_positions_stream_arn" {
  description = "ARN do DynamoDB Stream (CDC das posições dos entregadores)"
  value       = aws_dynamodb_table.courier_positions.stream_arn
}
