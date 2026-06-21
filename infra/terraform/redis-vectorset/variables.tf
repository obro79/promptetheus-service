variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Name tag / prefix for the instance and security group."
  type        = string
  default     = "redis8"
}

variable "instance_type" {
  description = "EC2 instance type for the Redis host."
  type        = string
  default     = "t3.micro"
}

variable "redis_password" {
  description = "Password set as Redis `requirepass`. Keep this in a tfvars file or TF_VAR_redis_password, never in VCS."
  type        = string
  sensitive   = true
}

variable "allowed_cidrs" {
  description = "CIDR blocks allowed to reach Redis on 6379. Restrict to your app's source; avoid 0.0.0.0/0."
  type        = list(string)
}

variable "subnet_id" {
  description = "Optional subnet to launch in. Defaults to the first subnet of the default VPC when empty."
  type        = string
  default     = ""
}

variable "associate_public_ip" {
  description = "Assign a public IP. Set false when the app reaches Redis privately within the VPC."
  type        = bool
  default     = true
}

variable "root_volume_size" {
  description = "Root EBS volume size (GiB). Redis AOF persistence is written here under /var/lib/redis."
  type        = number
  default     = 20
}

variable "redis_image" {
  description = "Redis container image. Must be Redis 8+ for Vector Sets (VADD/VSIM)."
  type        = string
  default     = "redis:8"
}

variable "key_name" {
  description = "Name of an existing EC2 key pair to enable SSH login. Empty means no key pair (SSH-by-key disabled)."
  type        = string
  default     = ""
}

variable "ssh_allowed_cidrs" {
  description = "CIDR blocks allowed to reach SSH on 22. Empty means no SSH ingress rule is created."
  type        = list(string)
  default     = []
}

variable "enable_ssm" {
  description = "Attach an IAM instance profile so AWS Systems Manager Session Manager works (keyless shell, no open SSH port). Requires IAM create permissions to apply."
  type        = bool
  default     = false
}

variable "manage_network_acl" {
  description = "Create a dedicated Network ACL for this box's subnet allowing Redis (6379) + ephemeral return traffic. Use when the VPC's default NACL is locked down (NACLs are stateless, so a restrictive default NACL silently breaks outbound too). Reassociates ONLY this subnet; other subnets keep the default NACL."
  type        = bool
  default     = false
}
