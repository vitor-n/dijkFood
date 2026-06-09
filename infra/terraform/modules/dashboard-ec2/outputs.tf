output "instance_id" {
  value = aws_instance.dashboard.id
}

output "public_ip" {
  value = aws_instance.dashboard.public_ip
}

output "public_dns" {
  value = aws_instance.dashboard.public_dns
}

output "url" {
  value = "http://${aws_instance.dashboard.public_dns}"
}
