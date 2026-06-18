# ──────────────────────────────────────────────────────────────────────────────
#  Athena — consulta serverless sobre os eventos do Firehose
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_athena_workgroup" "analytics" {
  name          = "${var.project_name}-analytics"
  description   = "DijkFood — dashboard analítico, features de ML e camada conversacional"
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.datalake.bucket}/athena-results/"
    }

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
  }
}
