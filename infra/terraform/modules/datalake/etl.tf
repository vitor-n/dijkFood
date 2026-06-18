# ──────────────────────────────────────────────────────────────────────────────
#  Glue ETL — raw (JSON) → curated → marts (PARQUET) via Athena CTAS
#
#  Job Python Shell (sem Spark): materializa fisicamente as camadas curated/marts
#  em Parquet, registradas no Glue Data Catalog. Script em s3://<bucket>/glue/.
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_glue_job" "build_marts" {
  name     = "${var.project_name}-build-marts"
  role_arn = var.glue_role_arn

  command {
    name            = "pythonshell"
    python_version  = "3.9"
    script_location = "s3://${aws_s3_bucket.datalake.bucket}/glue/build_marts.py"
  }

  default_arguments = {
    "--GLUE_DATABASE"    = aws_glue_catalog_database.analytics.name
    "--ATHENA_WORKGROUP" = aws_athena_workgroup.analytics.name
    "--DATALAKE_BUCKET"  = aws_s3_bucket.datalake.bucket
    "--job-language"     = "python"
  }

  max_capacity = 1.0
  timeout      = 30
  execution_property {
    max_concurrent_runs = 1
  }
}

# Agenda a transformação (curated/marts) periodicamente.
resource "aws_glue_trigger" "build_marts" {
  name     = "${var.project_name}-build-marts"
  type     = "SCHEDULED"
  schedule = var.etl_schedule

  actions {
    job_name = aws_glue_job.build_marts.name
  }

  start_on_creation = false
}
