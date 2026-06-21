output "instance_id" {
  description = "EC2 instance ID of the Redis host."
  value       = aws_instance.redis.id
}

output "public_ip" {
  description = "Public IP of the Redis host (null when associate_public_ip is false)."
  value       = aws_instance.redis.public_ip
}

output "private_ip" {
  description = "Private IP of the Redis host (use this when the app runs in the same VPC)."
  value       = aws_instance.redis.private_ip
}

output "security_group_id" {
  description = "Security group guarding Redis."
  value       = aws_security_group.redis.id
}

output "ssh_command" {
  description = "SSH command (only meaningful when key_name + ssh_allowed_cidrs are set)."
  value       = var.key_name != "" && var.associate_public_ip ? "ssh -i <path-to-${var.key_name}.pem> ec2-user@${aws_instance.redis.public_ip}" : "n/a (set key_name + ssh_allowed_cidrs, or use SSM: aws ssm start-session --target ${aws_instance.redis.id})"
}

output "redis_url" {
  description = "Connection string for PROMPTETHEUS REDIS_URL. The password is URL-encoded so special characters (@, +, /) parse correctly."
  value       = "redis://default:${urlencode(var.redis_password)}@${var.associate_public_ip ? aws_instance.redis.public_ip : aws_instance.redis.private_ip}:6379/0"
  sensitive   = true
}
