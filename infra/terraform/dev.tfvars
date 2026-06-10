aws_region   = "us-east-1"
environment  = "dev"
project_name = "dijkfood-g3-dev"

# ── Deploy de TESTE: rápido e barato ─────────────────────────────────────────
# Para a entrega final, volte db_multi_az=true e enable_ml_pipeline=true.
db_instance_class = "db.t3.small"
db_multi_az       = false # single-AZ sobe ~2x mais rápido

# Pipeline gerenciada (Step Functions + SageMaker + EventBridge + Model Registry):
# desligada no teste (parte mais sensível a permissão no Learner Lab). O ETA
# continua garantido pelo prediction-service no ECS (Fase 6 do guia).
enable_ml_pipeline = false

# Contagens em 1 → estabiliza o ECS mais rápido e corta custo (autoscaling
# continua provando o objetivo via *_max).
core_api_cpu     = 512
core_api_memory  = 1024
core_api_desired = 1
core_api_min     = 1
core_api_max     = 4

tracking_cpu     = 512
tracking_memory  = 1024
tracking_desired = 1
tracking_min     = 1
tracking_max     = 12

order_cpu     = 512
order_memory  = 1024
order_desired = 1
order_min     = 1
order_max     = 8

routing_cpu     = 1024
routing_memory  = 2048
routing_desired = 1
routing_min     = 1
routing_max     = 6

prediction_cpu     = 1024
prediction_memory  = 2048
prediction_desired = 1
prediction_min     = 1
prediction_max     = 1

assistant_cpu     = 512
assistant_memory  = 1024
assistant_desired = 1
assistant_min     = 1
assistant_max     = 2

dashboard_instance_type   = "t3.small"
load_tester_instance_type = "t3.medium"

db_username = "dijkfoodadmin"
db_password = "12345678"
