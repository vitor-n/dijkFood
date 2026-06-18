resource "aws_dynamodb_table" "courier_positions" {
  name         = "CourierTracking"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "ID_courier"

  # CDC para a camada analítica: posições reportadas viram eventos no Firehose
  # através da Lambda position-forwarder (sem impactar a latência da operação).
  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  attribute {
    name = "ID_courier"
    type = "N"
  }

  attribute {
    name = "cell_index"
    type = "S"
  }

  global_secondary_index {
    name               = "CellIndex"
    hash_key           = "cell_index"
    range_key          = "ID_courier"
    projection_type    = "INCLUDE"
    non_key_attributes = ["status", "lat", "lon", "updated_at"]
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = { Name = "CourierTracking" }
}
