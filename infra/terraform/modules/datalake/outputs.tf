output "firehose_stream_name" {
  description = "Nome do stream do Firehose criado"
  value       = aws_kinesis_firehose_delivery_stream.datalake_stream.name
}

output "firehose_stream_arn" {
  description = "ARN do stream do Firehose criado"
  value       = aws_kinesis_firehose_delivery_stream.datalake_stream.arn
}

output "datalake_bucket_name" {
  description = "Nome do bucket S3 do Datalake"
  value       = aws_s3_bucket.datalake.bucket
}

output "datalake_bucket_arn" {
  description = "ARN do bucket S3 do Datalake"
  value       = aws_s3_bucket.datalake.arn
}

output "glue_database_name" {
  description = "Nome do database no Glue Data Catalog"
  value       = aws_glue_catalog_database.analytics.name
}

output "glue_events_table_name" {
  description = "Nome da tabela canônica de eventos no Glue"
  value       = aws_glue_catalog_table.events.name
}

output "athena_workgroup_name" {
  description = "Workgroup do Athena para a camada analítica"
  value       = aws_athena_workgroup.analytics.name
}

output "athena_results_location" {
  description = "Local S3 dos resultados de query do Athena"
  value       = "s3://${aws_s3_bucket.datalake.bucket}/athena-results/"
}
