resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-operations"

  dashboard_body = jsonencode({
    widgets = [
      # ──────────────────────────────────────────────
      #  ECS CPU Utilization
      # ──────────────────────────────────────────────
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ServiceName", var.core_api_service_name, "ClusterName", var.ecs_cluster_name],
            [".", ".", ".", var.routing_service_name, ".", "."],
            [".", ".", ".", var.tracking_service_name, ".", "."],
            [".", ".", ".", var.order_service_name, ".", "."],
            [".", ".", ".", var.prediction_service_name, ".", "."]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "ECS CPU Utilization (%)"
        }
      },
      # ──────────────────────────────────────────────
      #  ECS HealthyHostCount (Tasks)
      # ──────────────────────────────────────────────
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "HealthyHostCount", "TargetGroup", var.core_api_tg_suffix, "LoadBalancer", var.alb_arn_suffix],
            [".", ".", ".", var.routing_tg_suffix, ".", "."],
            [".", ".", ".", var.tracking_tg_suffix, ".", "."],
            [".", ".", ".", var.order_tg_suffix, ".", "."],
            [".", ".", ".", var.prediction_tg_suffix, ".", "."]
          ]
          view    = "timeSeries"
          stacked = true
          region  = var.aws_region
          title   = "ECS Active Instances (Tasks)"
        }
      },
      # ──────────────────────────────────────────────
      #  ALB Health (Requests, Errors, Latency)
      # ──────────────────────────────────────────────
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "TargetGroup", var.core_api_tg_suffix, "LoadBalancer", var.alb_arn_suffix],
            [".", ".", ".", var.routing_tg_suffix, ".", "."],
            [".", ".", ".", var.tracking_tg_suffix, ".", "."],
            [".", ".", ".", var.order_tg_suffix, ".", "."],
            [".", ".", ".", var.prediction_tg_suffix, ".", "."]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Request Count by Service"
          stat    = "Sum"
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "TargetGroup", var.core_api_tg_suffix, "LoadBalancer", var.alb_arn_suffix],
            [".", ".", ".", var.routing_tg_suffix, ".", "."],
            [".", ".", ".", var.tracking_tg_suffix, ".", "."],
            [".", ".", ".", var.order_tg_suffix, ".", "."],
            [".", ".", ".", var.prediction_tg_suffix, ".", "."]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "5XX Errors by Service"
          stat    = "Sum"
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 6
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "TargetGroup", var.core_api_tg_suffix, "LoadBalancer", var.alb_arn_suffix],
            [".", ".", ".", var.routing_tg_suffix, ".", "."],
            [".", ".", ".", var.tracking_tg_suffix, ".", "."],
            [".", ".", ".", var.order_tg_suffix, ".", "."],
            [".", ".", ".", var.prediction_tg_suffix, ".", "."]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Latency by Service"
          stat    = "Average"
        }
      },
      # ──────────────────────────────────────────────
      #  DynamoDB
      # ──────────────────────────────────────────────
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", var.dynamodb_table_name, { "stat" : "Average" }],
            [".", "WriteThrottleEvents", ".", ".", { "stat" : "Sum", "yAxis" : "right" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "DynamoDB Writes & Throttles"
        }
      },
      # ──────────────────────────────────────────────
      #  RDS Connections
      # ──────────────────────────────────────────────
      {
        type   = "metric"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", var.rds_instance_id]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "RDS Connections"
        }
      },
      # ──────────────────────────────────────────────
      #  EC2 CPU Utilization
      # ──────────────────────────────────────────────
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/EC2", "CPUUtilization", "InstanceId", var.ec2_load_tester_id, { "label" : "load-tester" }],
            [".", ".", ".", var.ec2_dashboard_id, { "label" : "dashboard-ec2" }],
            [".", ".", ".", var.ec2_assistant_id, { "label" : "assistant-ec2" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "EC2 CPU Utilization (%)"
        }
      },
      # ──────────────────────────────────────────────
      #  Datalake (Firehose & Lambda)
      # ──────────────────────────────────────────────
      {
        type   = "metric"
        x      = 12
        y      = 18
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/Firehose", "DeliveryToS3.Records", "DeliveryStreamName", var.firehose_stream_name, { "stat" : "Sum" }],
            ["AWS/Lambda", "Invocations", "FunctionName", var.lambda_outbox_name, { "stat" : "Sum", "yAxis" : "right" }],
            [".", "Errors", ".", ".", { "stat" : "Sum", "yAxis" : "right", "color" : "#d62728" }]
          ]
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          title   = "Datalake (Firehose & Lambda)"
        }
      }
    ]
  })
}
