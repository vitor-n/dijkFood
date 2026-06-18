# ──────────────────────────────────────────────────────────────────────────────
#  Camada preditiva — pipeline GERENCIADA de retreino
#
#  EventBridge Scheduler ──▶ Step Functions ──▶ SageMaker Training Job (sklearn)
#                                          └────▶ Lambda ml-callback (promove
#                                                 artefato + recarrega serving +
#                                                 roda batch demanda/anomalias)
#
#  Serving do ETA é no ECS (prediction-service); aqui está apenas o ciclo de vida
#  gerenciado/agendado (coleta via Athena dentro do job de treino → modelo no S3).
# ──────────────────────────────────────────────────────────────────────────────

# ── Lambda de callback (promote + reload + batch) ──
data "archive_file" "ml_callback" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambda/ml_callback"
  output_path = "${path.module}/.build/ml_callback.zip"
  excludes    = ["__pycache__", "*.pyc"]
}

resource "aws_cloudwatch_log_group" "ml_callback" {
  name              = "/aws/lambda/${var.project_name}-ml-callback"
  retention_in_days = 7
}

resource "aws_lambda_function" "ml_callback" {
  function_name = "${var.project_name}-ml-callback"
  role          = var.role_arn
  handler       = "index.handler"
  runtime       = "python3.12"
  timeout       = 180
  memory_size   = 256

  filename         = data.archive_file.ml_callback.output_path
  source_code_hash = data.archive_file.ml_callback.output_base64sha256

  environment {
    variables = {
      DATALAKE_BUCKET     = var.datalake_bucket
      MODEL_PREFIX        = var.model_prefix
      PREDICTION_URL      = var.prediction_url
      MODEL_PACKAGE_GROUP = var.model_package_group
      SAGEMAKER_IMAGE     = var.training_image
    }
  }

  depends_on = [aws_cloudwatch_log_group.ml_callback]
}

# ── Step Functions state machine ──
resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${var.project_name}-eta-retrain"
  retention_in_days = 7
}

resource "aws_sfn_state_machine" "eta_retrain" {
  name     = "${var.project_name}-eta-retrain"
  role_arn = var.role_arn

  definition = templatefile("${path.module}/state_machine.asl.json", {
    training_image      = var.training_image
    role_arn            = var.role_arn
    sourcedir_s3        = "s3://${var.datalake_bucket}/${var.sourcedir_key}"
    output_s3           = "s3://${var.datalake_bucket}/${var.model_prefix}/sagemaker/"
    glue_database       = var.glue_database
    athena_workgroup    = var.athena_workgroup
    train_lookback_days = tostring(var.train_lookback_days)
    instance_type       = var.training_instance_type
    callback_lambda_arn = aws_lambda_function.ml_callback.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }
}

# ── EventBridge Scheduler — dispara o retreino periodicamente ──
resource "aws_scheduler_schedule" "eta_retrain" {
  name       = "${var.project_name}-eta-retrain"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "America/Sao_Paulo"

  target {
    arn      = aws_sfn_state_machine.eta_retrain.arn
    role_arn = var.role_arn

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}
