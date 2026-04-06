resource "aws_dynamodb_table" "courier_positions" {
  name         = "${var.project_name}-courier-positions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ID_courier"
  range_key    = "timestamp"

  attribute {
    name = "ID_courier"
    type = "N"
  }
/*
  attribute {
    name = "timestamp"
    type = "N"
  }

  attribute {
    name = "order_id"
    type = "S"
  }
*/
  global_secondary_index {
    name            = "CellIndex"
    hash_key        = "cell_index"
    range_key       = "ID_courier"
    projection_type = "ALL"
  }
/*
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
*/
  tags = { Name = "${var.project_name}-courier-positions" }
}
