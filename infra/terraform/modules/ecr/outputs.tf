output "repository_urls" {
  description = "Map of service name → ECR repository URL"
  value       = { for k, v in aws_ecr_repository.service : k => v.repository_url }
}

output "registry_id" {
  value = values(aws_ecr_repository.service)[0].registry_id
}
