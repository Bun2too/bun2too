# AWS ECS Fargate (secondary target)

Planned for phase 6 (execution plan). Same two images as `gcp-cloudrun`: an ALB in front of `relay-gateway`, `relay-agents` as an internal service, RDS Postgres 17, SQS for the ticket outbox, ADOT sidecar exporting to X-Ray. Track the work in a `spec` issue before writing modules here.
