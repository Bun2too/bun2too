# 0004. Railway for the support-agent POC, GCP Cloud Run as the GA candidate

- Status: accepted
- Date: 2026-11-16

## Context

The POC needs three environments within days, at low cost, with no cluster to run. Crew-team already deploys to Railway with Terraform (HCP state) and the Railway CLI, so the team knows the tooling and its quirks. Enterprise buyers will later ask for a major cloud, regional controls and immutable image promotion.

## Decision

- **POC:** one Railway project, `bun2too-support`, with environments `dev`, `qa` and `prod`. Services: `gateway`, `agents` and `postgres`.
- **Terraform** (`terraform-community-providers/railway`, HCP Terraform state) in two layers:
  - `project`: the project, environments and services. Applied rarely, behind approval.
  - `environment`: per-environment variables, secrets and domains. One workspace per environment, applied by the deploy job, so config is promoted like code.
- **Deploy** with `railway up --path-as-root`, the commit SHA as the message, then wait for that exact deployment to reach `SUCCESS`.
- **Volumes** are per-environment in Railway. They are created by `scripts/deploy/ensure-volume.sh`, not by the provider's nested `volume` block, which crew-team found unreliable on update.
- **GA candidate:** Google Cloud Run (`infra/terraform/gcp-cloudrun`), with images built once and promoted by digest.

## Consequences

- Railway builds each environment from source, so prod runs the same commit as qa but not a byte-identical image. Lockfiles and pinned base images keep the risk small. Cloud Run removes it at GA.
- Service-level settings (source, health check) are shared by all environments in one Railway project. Per-environment differences must be variables.
- The Railway API token must be an account or workspace token. The CLI misreads a `RAILWAY_TOKEN` as a project token, so the scripts unset it.
