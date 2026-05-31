output "firehose_stream_name" {
  description = "Nome do stream do Firehose criado"
  value       = aws_kinesis_firehose_delivery_stream.datalake_stream.name
}

output "datalake_bucket_name" {
  description = "Nome do bucket S3 do Datalake"
  value       = aws_s3_bucket.datalake.bucket
}
