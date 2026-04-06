resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "graph_data" {
  bucket        = "${var.project_name}-graph-data-${var.environment}-${random_id.bucket_suffix.hex}"
  force_destroy = true

  tags = { Name = "${var.project_name}-graph-data" }
}

resource "aws_s3_bucket_versioning" "graph_data" {
  bucket = aws_s3_bucket.graph_data.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "graph_data" {
  bucket = aws_s3_bucket.graph_data.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "graph_data" {
  bucket = aws_s3_bucket.graph_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
