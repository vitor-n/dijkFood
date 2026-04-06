aws_region   = "us-east-1"
environment  = "dev"
project_name = "dijkfood-g3-dev"

db_instance_class = "db.t3.micro"
db_multi_az       = false

core_api_cpu     = 512
core_api_memory  = 1024
core_api_desired = 1
core_api_min     = 1
core_api_max     = 2
tracking_cpu     = 512
tracking_memory  = 1024
tracking_desired = 1
tracking_min     = 1
tracking_max     = 2

order_cpu     = 512
order_memory  = 1024
order_desired = 1
order_min     = 1
order_max     = 2

routing_cpu     = 1024
routing_memory  = 2048
routing_desired = 1
routing_min     = 1
routing_max     = 2

db_username = "dijkfoodadmin"
db_password = "12345678"
