# Reproducible Redis 8 (Vector Sets) host for the fix-agent's "iris" similarity
# path. ElastiCache/MemoryDB do not offer Redis 8 Vector Sets (VADD/VSIM), so the
# vector path requires running Redis 8 ourselves; this module does that on a single
# locked-down EC2 instance with AOF persistence on its root volume.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Always-current Amazon Linux 2023 AMI for the chosen region.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

locals {
  subnet_id = var.subnet_id != "" ? var.subnet_id : data.aws_subnets.default.ids[0]

  user_data = <<-EOT
    #!/bin/bash
    dnf install -y docker
    systemctl enable --now docker
    docker run -d --name redis --restart unless-stopped -p 6379:6379 \
      -v /var/lib/redis:/data ${var.redis_image} \
      redis-server --requirepass '${var.redis_password}' --appendonly yes
  EOT
}

resource "aws_security_group" "redis" {
  name        = "${var.name}-sg"
  description = "Redis 8 (Vector Sets)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Redis"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  dynamic "ingress" {
    for_each = length(var.ssh_allowed_cidrs) > 0 ? [1] : []
    content {
      description = "SSH"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.ssh_allowed_cidrs
    }
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name}-sg"
  }
}

# Optional: IAM instance profile for SSM Session Manager (keyless shell, no open SSH).
resource "aws_iam_role" "ssm" {
  count = var.enable_ssm ? 1 : 0
  name  = "${var.name}-ssm-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  count      = var.enable_ssm ? 1 : 0
  role       = aws_iam_role.ssm[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ssm" {
  count = var.enable_ssm ? 1 : 0
  name  = "${var.name}-ssm-profile"
  role  = aws_iam_role.ssm[0].name
}

resource "aws_instance" "redis" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = var.instance_type
  subnet_id                   = local.subnet_id
  vpc_security_group_ids      = [aws_security_group.redis.id]
  associate_public_ip_address = var.associate_public_ip
  user_data                   = local.user_data
  key_name                    = var.key_name != "" ? var.key_name : null
  iam_instance_profile        = var.enable_ssm ? aws_iam_instance_profile.ssm[0].name : null

  root_block_device {
    volume_size = var.root_volume_size
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name = var.name
  }

  # user_data only runs at first boot; changing it (or the AMI) would force a
  # replacement and wipe the box. Change those deliberately, not on every apply.
  lifecycle {
    ignore_changes = [user_data, ami]
  }
}
