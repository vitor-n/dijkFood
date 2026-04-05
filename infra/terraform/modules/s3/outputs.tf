output "graph_bucket_name" {
  value = aws_s3_bucket.graph_data.bucket
}

output "graph_bucket_arn" {
  value = aws_s3_bucket.graph_data.arn
}
