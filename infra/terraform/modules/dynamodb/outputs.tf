output "courier_positions_table_name" {
  value = aws_dynamodb_table.courier_positions.name
}

output "courier_positions_table_arn" {
  value = aws_dynamodb_table.courier_positions.arn
}
