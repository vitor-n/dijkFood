aws_region   = "us-east-1"
environment  = "production"
project_name = "dijkfood-g3-prod"

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

routing_cpu     = 2048
routing_memory  = 2048
routing_desired = 2
routing_min     = 2
routing_max     = 6

load_tester_instance_type = "t3.medium"

db_username = "dijkfoodadmin"
db_password = "12345678"
