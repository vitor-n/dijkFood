# ──────────────────────────────────────────────────────────────────────────────
#  Glue Data Catalog — schema-on-read sobre o S3 que o Firehose alimenta
#
#  O Firehose grava JSON/GZIP em:
#    s3://<bucket>/raw/service-dumps/entidade=<E>/year=<Y>/month=<M>/day=<D>/
#
#  Definimos UMA tabela canônica `events` com particionamento por projeção
#  (partition projection) — sem necessidade de Glue Crawler nem MSCK REPAIR,
#  o que é ideal sob a restrição de só termos a LabRole.
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_glue_catalog_database" "analytics" {
  name        = "${var.project_name}_analytics"
  description = "DijkFood — camada analítica (eventos operacionais do Firehose)"
}

locals {
  events_location = "s3://${aws_s3_bucket.datalake.bucket}/raw/service-dumps/"
}

resource "aws_glue_catalog_table" "events" {
  name          = "events"
  database_name = aws_glue_catalog_database.analytics.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL           = "TRUE"
    classification     = "json"
    "compressionType"  = "gzip"
    has_encrypted_data = "false"

    # ── Partition projection (sem crawler) ──
    "projection.enabled"         = "true"
    "projection.entidade.type"   = "enum"
    "projection.entidade.values" = "Order,User,Restaurant,Courier,MenuItem,Position"
    "projection.year.type"       = "integer"
    "projection.year.range"      = "2024,2030"
    "projection.year.digits"     = "4"
    "projection.month.type"      = "integer"
    "projection.month.range"     = "1,12"
    "projection.month.digits"    = "2"
    "projection.day.type"        = "integer"
    "projection.day.range"       = "1,31"
    "projection.day.digits"      = "2"
    "storage.location.template"  = "${local.events_location}entidade=$${entidade}/year=$${year}/month=$${month}/day=$${day}"
  }

  partition_keys {
    name = "entidade"
    type = "string"
  }
  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }

  storage_descriptor {
    location      = local.events_location
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "events-json"
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      parameters = {
        "ignore.malformed.json" = "true"
        "dots.in.keys"          = "false"
        "case.insensitive"      = "true"
        # `timestamp` é palavra reservada no Athena — mapeamos para event_timestamp
        "mapping.event_timestamp" = "timestamp"
      }
    }

    # Envelope do evento
    columns {
      name = "event_timestamp"
      type = "string"
    }
    columns {
      name = "acao"
      type = "string"
    }

    # `dados` é a união (schema-on-read) de todos os payloads por entidade.
    # Campos ausentes para uma dada entidade resolvem para NULL.
    columns {
      name = "dados"
      type = "struct<id_order:bigint,created_at:string,id_restaurant:bigint,id_user:bigint,id_courier:bigint,id_last_state:int,id_state:int,name:string,email:string,phone:string,lat:double,lon:double,h3_index:bigint,id_cuisine_type:int,id_vehicle_type:int,id_item:bigint,status:string,cell_index:string,updated_at:bigint>"
    }
  }
}
