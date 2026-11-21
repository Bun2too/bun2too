# 0004. Railway for the support-agent POC, GCP Cloud Run as the GA candidate

- Status: accepted
- Date: 2026-11-16

## Context

The POC needs three environments within days, at low cost, with no cluster to run. Crew-team already deploys to Railway with Terraform (HCP state) and the Railway CLI, so the team knows the tooling and its quirks. Enterprise buyers will later ask for a major cloud, regional controls and immutable image promotion.

## Decision

- **POC:** one Railway project per environment: `bun2too-support-dev`, `bun2too-support-qa` and `bun2too-support-prod`. Each has one Railway environment named `dev`, `qa` or `prod`, and the services `gateway`, `agents` and `postgres`. (Amended 2026-11-21. It was one shared project with three environments, which needed a fourth HCP workspace and a separate workflow for the shared layer.)
- **Terraform** (`terraform-community-providers/railway`, HCP Terraform state): one module, `infra/terraform/railway`. Each environment has one HCP workspace with the same name as its Railway project, in the HCP project `bun2too-support-app`. The deploy job applies it, so the project, services, variables, secrets and domain are promoted like code.
- **Deploy** with `railway up --path-as-root`, the commit SHA as the message, then wait for that exact deployment to reach `SUCCESS`.
- **Volumes** are per-environment in Railway. They are created by `scripts/deploy/ensure-volume.sh`, not by the provider's nested `volume` block, which crew-team found unreliable on update.
- **GA candidate:** Google Cloud Run (`infra/terraform/gcp-cloudrun`), with images built once and promoted by digest.

## Consequences

- Railway builds each environment from source, so prod runs the same commit as qa but not a byte-identical image. Lockfiles and pinned base images keep the risk small. Cloud Run removes it at GA.
- Each environment owns its whole Railway project, so one name (`bun2too-support-<environment>`) identifies it in Railway and HCP Terraform, and in the `support-<environment>` GitHub environment. A service change (a new service, a health-check path) reaches dev first and is promoted like any other change.
- The Railway API token must be an account or workspace token. The CLI misreads a `RAILWAY_TOKEN` as a project token, so the scripts unset it.
