# ──────────────────────────────────────────────────────────────────────────────
#  position-forwarder — Lambda que leva o CDC do DynamoDB ao Firehose
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_pipes_pipe" "position_forwarder" {
  name     = "${var.project_name}-position-forwarder"
  role_arn = var.lambda_role_arn
  source   = var.dynamodb_stream_arn
  target   = var.firehose_stream_arn

  source_parameters {
    dynamodb_stream_parameters {
      starting_position                  = "LATEST"
      batch_size                         = 500
      maximum_batching_window_in_seconds = 30
      maximum_retry_attempts             = 3
    }
  }

  target_parameters {
    input_template = <<EOF
{
  "timestamp": "<aws.pipes.event.ingestion-time>",
  "entidade": "Position",
  "acao": "REPORT",
  "dados": {
    "id_courier": <$.dynamodb.NewImage.ID_courier.N>,
    "lat": <$.dynamodb.NewImage.lat.N>,
    "lon": <$.dynamodb.NewImage.lon.N>,
    "status": "<$.dynamodb.NewImage.status.S>",
    "cell_index": "<$.dynamodb.NewImage.cell_index.S>",
    "updated_at": <$.dynamodb.NewImage.updated_at.N>
  }
}
EOF
  }
}

# ──────────────────────────────────────────────────────────────────────────────
#  outbox-publisher — relay transacional do outbox (RDS) para o Firehose
# ──────────────────────────────────────────────────────────────────────────────

data "archive_file" "outbox_publisher" {
  type        = "zip"
  source_dir  = "${path.module}/../../../lambda/outbox_publisher"
  output_path = "${path.module}/.build/outbox_publisher.zip"
  excludes    = ["__pycache__", "*.pyc", "_vendor/**/__pycache__", "_vendor/**/*.pyc"]
}

resource "aws_cloudwatch_log_group" "outbox_publisher" {
  name              = "/aws/lambda/${var.project_name}-outbox-publisher"
  retention_in_days = 7
}

resource "aws_lambda_function" "outbox_publisher" {
  function_name = "${var.project_name}-outbox-publisher"
  role          = var.lambda_role_arn
  handler       = "index.handler"
  runtime       = "python3.12"
  timeout       = 120
  memory_size   = 256

  filename         = data.archive_file.outbox_publisher.output_path
  source_code_hash = data.archive_file.outbox_publisher.output_base64sha256

  vpc_config {
    subnet_ids         = var.vpc_subnet_ids
    security_group_ids = [var.lambda_security_group_id]
  }

  environment {
    variables = {
      FIREHOSE_STREAM_NAME = var.firehose_stream_name
      DB_HOST              = var.db_host
      DB_PORT              = "5432"
      DB_NAME              = var.db_name
      DB_USER              = var.db_user
      DB_PASSWORD          = var.db_password
    }
  }

  depends_on = [aws_cloudwatch_log_group.outbox_publisher]
}

# Dispara o publisher periodicamente (near-real-time para a camada analítica).
resource "aws_cloudwatch_event_rule" "outbox_tick" {
  name                = "${var.project_name}-outbox-tick"
  schedule_expression = var.outbox_schedule
}

resource "aws_cloudwatch_event_target" "outbox_tick" {
  rule = aws_cloudwatch_event_rule.outbox_tick.name
  arn  = aws_lambda_function.outbox_publisher.arn
}

resource "aws_lambda_permission" "outbox_tick" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.outbox_publisher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.outbox_tick.arn
}
