aws_region   = "us-east-1"
environment  = "dev"
project_name = "dijkfood-g3-dev"

db_instance_class = "db.t3.small"
db_multi_az       = true

core_api_cpu     = 512
core_api_memory  = 1024
core_api_desired = 2
core_api_min     = 2
core_api_max     = 4

tracking_cpu     = 512
tracking_memory  = 1024
tracking_desired = 3
tracking_min     = 3
tracking_max     = 12

order_cpu     = 512
order_memory  = 1024
order_desired = 2
order_min     = 2
order_max     = 8

routing_cpu     = 1024
routing_memory  = 2048
routing_desired = 2
routing_min     = 2
routing_max     = 6

# Serviços do Objetivo 3 (mantidos pequenos p/ custo do Learner Lab)
dashboard_cpu     = 512
dashboard_memory  = 1024
dashboard_desired = 1
dashboard_min     = 1
dashboard_max     = 2

prediction_cpu     = 1024
prediction_memory  = 2048
prediction_desired = 1
prediction_min     = 1
prediction_max     = 1

load_tester_instance_type = "t3.medium"

db_username = "dijkfoodadmin"
db_password = "12345678"
