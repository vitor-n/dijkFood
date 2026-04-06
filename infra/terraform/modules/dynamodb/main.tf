resource "aws_dynamodb_table" "courier_positions" {
  name         = "CourierTracking"
  billing_mode = "PROVISIONED"
  hash_key     = "ID_courier"

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
    read_capacity      = 10
    write_capacity     = 10
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = { Name = "CourierTracking" }
}
