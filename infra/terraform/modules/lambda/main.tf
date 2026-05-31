# ──────────────────────────────────────────────────────────────────────────
#  Lambda: position-forwarder
#  DynamoDB Streams (CourierTracking) ──> Firehose (eventos courier_position)
#  CDC sem adicionar latência ao caminho operacional de tracking.
# ──────────────────────────────────────────────────────────────────────────

terraform {
  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.0"
    }
  }
}

data "archive_file" "position_forwarder" {
  type        = "zip"
  source_file = "${path.root}/../lambda/position_forwarder/index.py"
  output_path = "${path.module}/.build/position_forwarder.zip"
}

resource "aws_cloudwatch_log_group" "position_forwarder" {
  name              = "/aws/lambda/${var.project_name}-position-forwarder"
  retention_in_days = 7
}

resource "aws_lambda_function" "position_forwarder" {
  function_name = "${var.project_name}-position-forwarder"
  role          = var.lab_role_arn
  runtime       = "python3.12"
  handler       = "index.handler"
  timeout       = 60
  memory_size   = 256

  filename         = data.archive_file.position_forwarder.output_path
  source_code_hash = data.archive_file.position_forwarder.output_base64sha256

  environment {
    variables = {
      FIREHOSE_STREAM_NAME = var.firehose_stream_name
      CITY                 = var.city
    }
  }

  depends_on = [aws_cloudwatch_log_group.position_forwarder]
}

resource "aws_lambda_event_source_mapping" "ddb_stream" {
  event_source_arn  = var.dynamodb_stream_arn
  function_name     = aws_lambda_function.position_forwarder.arn
  starting_position = "LATEST"

  # Lotes grandes + janela ampla: maximizam o colapso "última posição por
  # courier" feito na Lambda (menos volume/custo no Firehose). A latência
  # analítica extra (~15s) é irrelevante para o dashboard batch.
  batch_size                         = 1000
  maximum_batching_window_in_seconds = 15
  parallelization_factor             = 2

  # Posições são best-effort para a analítica: não retém o shard em erro.
  bisect_batch_on_function_error = false
  maximum_retry_attempts         = 2
}
