resource "aws_dynamodb_table" "courier_positions" {
  name         = "CourierTracking"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "ID_courier"

  # CDC source for the analytics layer (Objetivo 3): a Lambda consumes this
  # stream and forwards courier-position events to Firehose, adding ZERO latency
  # to the tracking write path (no SLA regression). PAY_PER_REQUEST escala
  # instantaneamente sob pico/evento sem risco de throttling (e não aceita
  # read/write_capacity — daí a remoção).
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

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
