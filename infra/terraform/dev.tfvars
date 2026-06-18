aws_region   = "us-east-1"
environment  = "dev"
project_name = "dijkfood-g3-dev"

# ── Deploy de TESTE: rápido e barato ─────────────────────────────────────────
# Para a entrega final, volte db_multi_az=true e enable_ml_pipeline=true.
db_instance_class = "db.t3.large"  # upgrade: 8GB RAM / ~840 conn (compatível AWS Academy)
db_multi_az       = false # single-AZ sobe ~2x mais rápido

# Pipeline gerenciada (Step Functions + SageMaker + EventBridge + Model Registry):
# desligada no teste (parte mais sensível a permissão no Learner Lab). O ETA
# continua garantido pelo prediction-service no ECS (Fase 6 do guia).
enable_ml_pipeline = false

# Contagens em 1 → estabiliza o ECS mais rápido e corta custo (autoscaling
# continua provando o objetivo via *_max).
core_api_cpu     = 512
core_api_memory  = 1024
core_api_desired = 2
core_api_min     = 2
core_api_max     = 6

tracking_cpu     = 1024
tracking_memory  = 2048
tracking_desired = 8
tracking_min     = 8
tracking_max     = 20

order_cpu     = 1024
order_memory  = 2048
order_desired = 4
order_min     = 4
order_max     = 12

routing_cpu     = 2048
routing_memory  = 4096
routing_desired = 2
routing_min     = 2
routing_max     = 8

prediction_cpu     = 1024
prediction_memory  = 2048
prediction_desired = 1
prediction_min     = 1
prediction_max     = 1

assistant_instance_type = "t3.micro"

dashboard_instance_type   = "t3.small"
load_tester_instance_type = "t3.large"

db_username = "dijkfoodadmin"
db_password = "12345678"
