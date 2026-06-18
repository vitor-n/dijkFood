output "state_machine_arn" {
  value = aws_sfn_state_machine.eta_retrain.arn
}

output "callback_lambda_name" {
  value = aws_lambda_function.ml_callback.function_name
}

output "schedule_name" {
  value = aws_scheduler_schedule.eta_retrain.name
}
