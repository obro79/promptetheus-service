# Terraform: Redis 8 (Vector Sets) host

Provisions a single locked-down EC2 instance running **Redis 8** in Docker with
AOF persistence, for the fix-agent's vector similarity path (`memory.py` →
`VADD`/`VSIM`). AWS ElastiCache/MemoryDB top out at Redis OSS 7.1 / Valkey 8,
**neither of which has Vector Sets**, so the vector path requires running Redis 8
ourselves. Without `REDIS_URL` the service degrades to no-ops; with a Redis < 8 it
still works but falls back to the lexical similarity scan.

## What it creates
- `aws_security_group.redis` — inbound `6379` from `allowed_cidrs` only.
- `aws_instance.redis` — Amazon Linux 2023 (latest AMI via SSM), `user_data` installs
  Docker and runs `redis:8` with `--requirepass` + `--appendonly yes`, AOF on an
  encrypted gp3 root volume.

## Usage
```bash
cd infra/terraform/redis-vectorset
cp terraform.tfvars.example terraform.tfvars   # fill in password + allowed_cidrs
terraform init
terraform plan
terraform apply
terraform output -raw redis_url                # -> set as PROMPTETHEUS REDIS_URL
```
Credentials come from the standard AWS provider chain (`AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION`, an AWS profile, or an instance role).

## Adopting an existing hand-made box (no recreate)
If you already launched the instance + SG manually, import them so Terraform manages
them instead of creating duplicates (replace the IDs):
```bash
terraform import aws_security_group.redis sg-03ded79cdbf2e6712
terraform import aws_instance.redis      i-00f1dc69aaaf02bbe
terraform plan   # should show no destructive changes (user_data/ami are ignored)
```

## Shell / SSH access
The instance has no key pair by default. Two ways to get a shell:

- **SSH (key-based):** set `key_name` to an existing EC2 key pair and `ssh_allowed_cidrs`
  to your admin IP, then `terraform apply` and `terraform output ssh_command`
  (`ssh -i <key>.pem ec2-user@<ip>`). Note: adding a key pair to an *already-running*
  instance forces a replacement, so set this before first apply (or plan to recreate).
- **SSM Session Manager (keyless, no open port — recommended):** set `enable_ssm = true`.
  This attaches an instance profile with `AmazonSSMManagedInstanceCore`; then
  `aws ssm start-session --target <instance_id>` with no SSH port open at all.
  Applying this requires IAM create permissions (role + instance profile); the
  `devin-iac` user as scoped (`AmazonEC2FullAccess` + `AmazonSSMReadOnlyAccess`) cannot
  create the role — broaden to include IAM, or create the role out-of-band.

## Security notes
- `allowed_cidrs` must be as tight as possible. Prefer running the FastAPI service in
  this VPC and allowing its security group (swap the `cidr_blocks` ingress for a
  `security_groups` ingress) over opening a public CIDR.
- This serves plaintext `redis://` guarded by the password. For production, terminate
  TLS (`rediss://`) — e.g. via stunnel/native Redis TLS — or keep Redis private and
  reach it only from inside the VPC.
- `redis_password` and `redis_url` live in Terraform **state**. State is gitignored
  here; use a remote encrypted backend (S3 + DynamoDB lock) for team use.

## State backend
Defaults to local state (gitignored). To share state, add a `backend "s3"` block in
`versions.tf` and re-run `terraform init -migrate-state`.
