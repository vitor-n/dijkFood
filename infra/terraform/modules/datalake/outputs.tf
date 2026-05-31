output "firehose_stream_name" {
  description = "Nome do stream do Firehose criado"
  value       = aws_kinesis_firehose_delivery_stream.datalake_stream.name
}

output "datalake_bucket_name" {
  description = "Nome do bucket S3 do Datalake"
  value       = aws_s3_bucket.datalake.bucket
}

output "glue_database_name" {
  description = "Banco do Glue Data Catalog com a tabela de eventos"
  value       = aws_glue_catalog_database.analytics.name
}

output "events_table_name" {
  description = "Tabela canônica de eventos (Parquet)"
  value       = aws_glue_catalog_table.events.name
}

output "athena_workgroup_name" {
  description = "Workgroup do Athena para a camada analítica"
  value       = aws_athena_workgroup.analytics.name
}
