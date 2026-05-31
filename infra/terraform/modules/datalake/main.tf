resource "random_id" "bucket_suffix" {
  byte_length = 4
}

#  Bucket S3 (Camada Raw do Datalake)
resource "aws_s3_bucket" "datalake" {
  bucket        = "${var.project_name}-datalake-${var.environment}-${random_id.bucket_suffix.hex}"
  force_destroy = true
  tags          = { Name = "${var.project_name}-datalake" }
}

# ──────────────────────────────────────────────
#  Firehose Delivery Stream
# ──────────────────────────────────────────────
resource "aws_kinesis_firehose_delivery_stream" "datalake_stream" {
  name        = "${var.project_name}-datalake-stream-${var.environment}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = var.firehose_role_arn
    bucket_arn = aws_s3_bucket.datalake.arn


    buffering_size     = 128
    buffering_interval = 300

    # TÓPICO 3: Compressão
    compression_format = "GZIP"


    dynamic_partitioning_configuration {
      enabled = true
    }

    # Estrutura de pastas no S3 (sucesso e erro)
    prefix              = "raw/service-dumps/entidade=!{partitionKeyFromQuery:entidade}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "error/service-dumps/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"

    # Processador JQ para extrair o valor da chave "entidade" do seu JSON
    processing_configuration {
      enabled = true
      
      processors {
        type = "MetadataExtraction"
        parameters {
          parameter_name  = "MetadataExtractionQuery"
          parameter_value = "{entidade:.entidade}"
        }
        parameters {
          parameter_name  = "JsonParsingEngine"
          parameter_value = "JQ-1.6"
        }
      }
    }
  }
}
