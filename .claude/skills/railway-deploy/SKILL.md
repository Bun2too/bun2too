---
name: railway-deploy
description: Plan, deploy, verify or roll back a Bun2too service on Railway (the support agent's dev/qa/prod, or crew-team). Use when changing Railway Terraform, the deploy workflows, or diagnosing a failed Railway deploy.
---

# Railway deploy

Read [docs/sop/environments-and-release.md](../../../docs/sop/environments-and-release.md) and [ADR 0004](../../../docs/adr/0004-railway-poc-gcp-ga.md) first. Crew-team has its own pipeline and skill (`bun2too-crew-team/.agents/skills/railway-deployment`); the lessons below came from it and apply to both.

## Rules

1. **Deploys run in CI, not from a laptop.** Locally, `terraform apply` and `railway up` are denied by `.claude/settings.json`. Change the code, then let `deploy-support.yml` promote it.
2. **Name the environment explicitly every time** (`--environment dev|qa|prod`). Service settings are shared across environments in one Railway project, so anything that differs per environment must be a variable in the `environment` Terraform layer.
3. **Use an account or workspace token as `RAILWAY_API_TOKEN`.** Unset `RAILWAY_TOKEN` before calling the CLI, because the CLI treats it as a project token and prefers it.
4. **Wait for the exact deployment ID** returned by `railway up --detach --json` to reach `SUCCESS`. A healthy older deployment proves nothing about the new one.
5. **Volumes are per environment.** Create them with `scripts/deploy/ensure-volume.sh`, never by toggling the provider's nested `volume` block. Never delete or replace a volume to fix a deploy.
6. **Never retry a mutation blindly.** A timeout can follow a success. Read state first (deployment status, volume list), then decide.
7. **Prod smoke is read-only.** Use `/healthz` and the agent card. Never create tickets in prod's Jira or ServiceNow from CI.

## Diagnose a failed deploy

1. Open the run summary. Note the environment, commit SHA and deployment ID.
2. Check the deployment status without redeploying: `scripts/deploy/railway-up.sh --wait-for <deployment-id>`.
3. Read logs in Railway (`railway logs --deployment <id> --environment <env>`) and quote sanitised errors only.
4. For a config cause, fix it in the `environment` layer and let the pipeline re-run. For a code cause, roll back (see the SOP) and open an issue with the evidence.

Report what is planned, what is deployed and what is verified as three separate facts.
