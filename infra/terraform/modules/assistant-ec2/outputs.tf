output "instance_id" {
  description = "ID da EC2"
  value       = aws_instance.assistant.id
}

output "public_ip" {
  description = "IP Público da EC2"
  value       = aws_instance.assistant.public_ip
}
