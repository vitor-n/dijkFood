"""
build_marts.py — Glue (Python Shell) job: raw (JSON) → curated → marts (PARQUET).

Materializa fisicamente a arquitetura medallion mostrada no diagrama:
  - raw      : eventos brutos do Firehose (JSON/GZIP) — tabela `events`.
  - curated  : fatos limpos/conformados em **Parquet** (curated_*).
  - marts    : agregados prontos para consumo em **Parquet** (mart_*).

Usa Athena CTAS (CREATE TABLE AS) — cada tabela vira Parquet registrado no Glue
Data Catalog, consultável pelo Athena. Sem Spark (Python Shell barato), o que
casa bem com a restrição de só termos a LabRole.

Args (default_arguments do Glue job):
  --GLUE_DATABASE --ATHENA_WORKGROUP --DATALAKE_BUCKET
"""
import sys
import time

import boto3

try:
    from awsglue.utils import getResolvedOptions
    args = getResolvedOptions(sys.argv, ["GLUE_DATABASE", "ATHENA_WORKGROUP", "DATALAKE_BUCKET"])
except Exception:
    # Permite execução fora do Glue (debug local) via env.
    import os
    args = {
        "GLUE_DATABASE": os.environ["GLUE_DATABASE"],
        "ATHENA_WORKGROUP": os.environ["ATHENA_WORKGROUP"],
        "DATALAKE_BUCKET": os.environ["DATALAKE_BUCKET"],
    }

DB = args["GLUE_DATABASE"]
WG = args["ATHENA_WORKGROUP"]
BUCKET = args["DATALAKE_BUCKET"]

athena = boto3.client("athena")
s3 = boto3.client("s3")


def run(sql):
    qid = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DB},
        WorkGroup=WG,
    )["QueryExecutionId"]
    while True:
        st = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        state = st["State"]
        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Athena {state}: {st.get('StateChangeReason', '')}\nSQL: {sql[:300]}")
        time.sleep(1.5)


def clear_prefix(prefix):
    paginator = s3.get_paginator("list_objects_v2")
    to_delete = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            to_delete.append({"Key": obj["Key"]})
            if len(to_delete) == 1000:
                s3.delete_objects(Bucket=BUCKET, Delete={"Objects": to_delete})
                to_delete = []
    if to_delete:
        s3.delete_objects(Bucket=BUCKET, Delete={"Objects": to_delete})


def materialize(name, layer, select_sql):
    location = f"s3://{BUCKET}/{layer}/{name}/"
    print(f"[ETL] {layer}.{name} -> {location}")
    clear_prefix(f"{layer}/{name}/")          # CTAS exige destino vazio
    run(f"DROP TABLE IF EXISTS {name}")
    run(f"CREATE TABLE {name} WITH (format='PARQUET', external_location='{location}') AS {select_sql}")


# ── Raw → views lógicas reaproveitadas pelas CTAS ──
_RAW_CTES = """
WITH orders_created AS (
    SELECT dados.id_order AS id_order, from_iso8601_timestamp(event_timestamp) AS created_at,
           dados.id_restaurant AS id_restaurant, dados.id_user AS id_user, dados.id_courier AS id_courier
    FROM events WHERE entidade='Order' AND acao='CREATE' AND dados.id_order IS NOT NULL
),
transitions AS (
    SELECT dados.id_order AS id_order, 1 AS id_state, from_iso8601_timestamp(event_timestamp) AS changed_at
    FROM events WHERE entidade='Order' AND acao='CREATE' AND dados.id_order IS NOT NULL
    UNION ALL
    SELECT dados.id_order, dados.id_state, from_iso8601_timestamp(event_timestamp)
    FROM events WHERE entidade='Order' AND acao='UPDATE' AND dados.id_order IS NOT NULL
),
restaurants AS (
    SELECT dados.id_restaurant AS id_restaurant, max(dados.name) AS name, max(dados.h3_index) AS region
    FROM events WHERE entidade='Restaurant' AND dados.id_restaurant IS NOT NULL GROUP BY dados.id_restaurant
)
"""


def main():
    # ── CURATED (fatos limpos, Parquet) ──
    materialize("curated_orders", "curated", _RAW_CTES + """
        SELECT o.id_order, o.created_at, o.id_restaurant, o.id_user, o.id_courier,
               r.region, r.name AS restaurant_name
        FROM orders_created o LEFT JOIN restaurants r ON o.id_restaurant = r.id_restaurant
    """)

    materialize("curated_deliveries", "curated", _RAW_CTES + """
        , lifecycle AS (
            SELECT o.id_order, o.created_at, o.id_restaurant, r.region,
                   min(CASE WHEN t.id_state=6 THEN t.changed_at END) AS delivered_at
            FROM orders_created o JOIN transitions t ON o.id_order=t.id_order
            LEFT JOIN restaurants r ON o.id_restaurant=r.id_restaurant
            GROUP BY o.id_order, o.created_at, o.id_restaurant, r.region
        )
        SELECT id_order, created_at, delivered_at, id_restaurant, region,
               date_diff('second', created_at, delivered_at)/60.0 AS delivery_minutes
        FROM lifecycle WHERE delivered_at IS NOT NULL
          AND date_diff('second', created_at, delivered_at) BETWEEN 0 AND 21600
    """)

    materialize("curated_positions", "curated", """
        SELECT dados.id_courier AS id_courier, dados.lat AS lat, dados.lon AS lon,
               dados.status AS status, from_iso8601_timestamp(event_timestamp) AS reported_at
        FROM events WHERE entidade='Position' AND dados.id_courier IS NOT NULL
    """)

    # ── MARTS (agregados prontos, Parquet) — reutilizam as curated ──
    materialize("mart_daily_volume", "marts",
                "SELECT date(created_at) AS day, count(*) AS orders FROM curated_orders GROUP BY 1")

    materialize("mart_region_distribution", "marts",
                "SELECT region, count(*) AS orders FROM curated_orders WHERE region IS NOT NULL GROUP BY region")

    materialize("mart_top_restaurants", "marts",
                "SELECT id_restaurant, max(restaurant_name) AS name, count(*) AS orders "
                "FROM curated_orders GROUP BY id_restaurant ORDER BY orders DESC LIMIT 50")

    materialize("mart_demand_heatmap", "marts",
                "SELECT day_of_week(created_at) AS dow, hour(created_at) AS hr, count(*) AS orders "
                "FROM curated_orders GROUP BY 1, 2")

    materialize("mart_delivery_histogram", "marts",
                "SELECT CAST(floor(delivery_minutes/5)*5 AS integer) AS bin_min, count(*) AS orders "
                "FROM curated_deliveries GROUP BY 1 ORDER BY 1")

    materialize("mart_state_avg_seconds", "marts", _RAW_CTES + """
        , seq AS (
            SELECT id_state, changed_at,
                   lead(changed_at) OVER (PARTITION BY id_order ORDER BY changed_at) AS next_at
            FROM transitions
        )
        SELECT id_state, avg(date_diff('second', changed_at, next_at)) AS avg_seconds, count(*) AS samples
        FROM seq WHERE next_at IS NOT NULL GROUP BY id_state
    """)

    print("[ETL] concluído: curated + marts materializados em Parquet.")


if __name__ == "__main__":
    main()
