# ──────────────────────────────────────────────────────────────────────────
#  Datalake (camada analítica obrigatória — Objetivo 3)
#
#  Captura de eventos (sem regredir o SLA da operação):
#    order-service / core-api ──(PutRecord, BackgroundTasks)──┐
#    DynamoDB Streams ──> Lambda position-forwarder ──────────┤
#                                                             ▼
#                            Kinesis Firehose (DirectPut) ──> S3 (Parquet, SNAPPY)
#
#  Firehose converte JSON -> PARQUET na entrega (data format conversion),
#  reduzindo custo de armazenamento e de scan no Athena. Esquema canônico
#  único (flat) descrito pela tabela Glue `events`, consultável via Athena
#  com partition projection (dt + hour) — sem crawler.
#
#  Toda compute usa a LabRole pré-existente (Learner Lab não cria IAM novo).
# ──────────────────────────────────────────────────────────────────────────

locals {
  glue_db = replace("${var.project_name}_analytics", "-", "_")
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# ── Bucket S3 do datalake (raw Parquet / athena-results / curated / models) ──

resource "aws_s3_bucket" "datalake" {
  bucket        = "${var.project_name}-datalake-${var.environment}-${random_id.bucket_suffix.hex}"
  force_destroy = true
  tags          = { Name = "${var.project_name}-datalake" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "datalake" {
  bucket = aws_s3_bucket.datalake.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "datalake" {
  bucket                  = aws_s3_bucket.datalake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Glue Data Catalog ──

resource "aws_glue_catalog_database" "analytics" {
  name = local.glue_db
}

# Tabela canônica de eventos (Parquet), com PARTITION PROJECTION (dt + hour)
# — sem crawler, scans paralelos e baratos no Athena. Também serve de schema
# para a conversão JSON->Parquet do Firehose.
resource "aws_glue_catalog_table" "events" {
  name          = "events"
  database_name = aws_glue_catalog_database.analytics.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                = "parquet"
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.range"         = "2026-01-01,NOW"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "projection.hour.type"        = "integer"
    "projection.hour.range"       = "0,23"
    "projection.hour.digits"      = "2"
    "storage.location.template"   = "s3://${aws_s3_bucket.datalake.bucket}/raw/dt=$${dt}/hour=$${hour}/"
    "EXTERNAL"                    = "TRUE"
  }

  partition_keys {
    name = "dt"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.datalake.bucket}/raw/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    columns {
      name = "event_type"
      type = "string"
    }
    columns {
      name = "occurred_at"
      type = "string"
    }
    columns {
      name = "city"
      type = "string"
    }
    columns {
      name = "order_id"
      type = "bigint"
    }
    columns {
      name = "restaurant_id"
      type = "bigint"
    }
    columns {
      name = "user_id"
      type = "bigint"
    }
    columns {
      name = "courier_id"
      type = "bigint"
    }
    columns {
      name = "state_id"
      type = "int"
    }
    columns {
      name = "state_name"
      type = "string"
    }
    columns {
      name = "lat"
      type = "double"
    }
    columns {
      name = "lon"
      type = "double"
    }
    columns {
      name = "h3_cell"
      type = "string"
    }
    columns {
      name = "predicted_eta_s"
      type = "double"
    }
  }
}

# ──────────────────────────────────────────────
#  Firehose Delivery Stream (DirectPut → S3 Parquet)
# ──────────────────────────────────────────────

resource "aws_kinesis_firehose_delivery_stream" "datalake_stream" {
  name        = "${var.project_name}-datalake-stream-${var.environment}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = var.firehose_role_arn
    bucket_arn = aws_s3_bucket.datalake.arn

    buffering_size     = var.firehose_buffer_mb
    buffering_interval = var.firehose_buffer_seconds

    # Conversão p/ Parquet faz a própria compressão (SNAPPY); o wrapper S3 deve
    # ficar UNCOMPRESSED (GZIP é incompatível com data format conversion).
    compression_format = "UNCOMPRESSED"

    # Prefixo Hive-style por tempo (compatível com partition projection),
    # sem dynamic partitioning (mais simples e barato).
    prefix              = "raw/dt=!{timestamp:yyyy-MM-dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "errors/!{firehose:error-output-type}/dt=!{timestamp:yyyy-MM-dd}/"

    # JSON de entrada -> Parquet de saída, usando o schema da tabela Glue.
    data_format_conversion_configuration {
      input_format_configuration {
        deserializer {
          open_x_json_ser_de {}
        }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de {}
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.analytics.name
        table_name    = aws_glue_catalog_table.events.name
        role_arn      = var.firehose_role_arn
        region        = var.aws_region
      }
    }

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = "/aws/kinesisfirehose/${var.project_name}-datalake-stream"
      log_stream_name = "S3Delivery"
    }
  }
}

# ── Athena workgroup (resultados no próprio datalake) ──

resource "aws_athena_workgroup" "analytics" {
  name          = "${var.project_name}-analytics"
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.datalake.bucket}/athena-results/"
    }
  }
}
