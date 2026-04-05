resource "aws_dynamodb_table" "courier_positions" {
  name         = "${var.project_name}-courier-positions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "courier_id"
  range_key    = "timestamp"

  attribute {
    name = "courier_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "N"
  }

  attribute {
    name = "order_id"
    type = "S"
  }

  global_secondary_index {
    name            = "order-positions-index"
    hash_key        = "order_id"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = { Name = "${var.project_name}-courier-positions" }
}
