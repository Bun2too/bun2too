# SOP: environments and release (support agent)

| Environment | Railway environment | Trigger                                                 | Data and integrations                                         | Who approves      |
| ----------- | ------------------- | ------------------------------------------------------- | ------------------------------------------------------------- | ----------------- |
| dev         | `dev`               | every merge to `main` that touches the support agent    | Offline mode: stand-in model and ticket systems               | nobody            |
| qa          | `qa`                | dev smoke passes                                        | Live model, Jira and ServiceNow **sandboxes**                 | nobody            |
| prod        | `prod`              | qa smoke and eval pass                                  | Live model; production Jira and ServiceNow for the tenant     | `support-prod` reviewers |

All three environments live in one Railway project, `bun2too-support`, and run the same three services: `gateway` (public), `agents` (private network only) and `postgres` (volume per environment).

## How a release flows

```
merge to main
  └─ deploy-support.yml
       verify (pnpm check on the exact commit)
       └─ dev   terraform apply (environment layer) → railway up gateway + agents → smoke + intake journey
          └─ qa terraform apply → railway up → smoke + intake journey + escalation journey + offline eval
             └─ prod  [human approval] → terraform apply → railway up → smoke (read-only, no tickets created)
```

Each environment gets the same commit SHA, recorded as the Railway deployment message. Railway builds each environment from that commit's source with lockfiles and pinned base images. On GCP (GA), the pipeline will build once and promote one immutable image digest instead; see [ADR 0004](../adr/0004-railway-poc-gcp-ga.md).

## Configuration changes

- Runtime variables and secrets are applied by the environment Terraform layer in the same deploy job, so config is promoted dev → qa → prod like code.
- Project-level changes (new service, health-check path) go through `infra-support.yml`, which plans and applies on merge to `main` in the `infra-support` environment (main only). PRs get credential-free checks in `ci.yml`, because a plan runs PR-controlled Terraform.

## Rollback

1. Actions → `deploy-support` → **Run workflow**. Choose the environment and the last good commit SHA.
2. The run re-applies that commit's config and redeploys its source. Prod still needs approval.
3. If config is not the cause, a faster path is to redeploy the previous deployment in the Railway dashboard. Record it in the incident notes.

## Secrets and variables (per GitHub environment `support-dev`, `support-qa`, `support-prod`)

| Name                       | Kind     | Holds                                                                                          |
| -------------------------- | -------- | ---------------------------------------------------------------------------------------------- |
| `RAILWAY_API_TOKEN`        | secret   | Railway account or workspace token (not a project token)                                      |
| `TF_API_TOKEN`             | secret   | HCP Terraform token                                                                            |
| `SUPPORT_RUNTIME_SECRETS`  | secret   | JSON map: `RELAY_TENANT_KEYS` (all environments), plus `ANTHROPIC_API_KEY`, the Cloudflare AI Gateway `CF_AIG_*` keys, `BUN2TOO_JIRA_*` and `BUN2TOO_SNOW_*` in qa and prod. What each key is and how to obtain it: [runtime secrets](../../bun2too-support-agent/docs/runtime-secrets.md) |
| `SMOKE_TENANT_KEY`         | secret   | A tenant API key that the smoke journey may use; must be one of the keys in `RELAY_TENANT_KEYS` |
| `TF_CLOUD_ORGANIZATION`    | variable | HCP Terraform organisation                                                                     |

The `support-prod` environment has required reviewers. `infra-support` (main only) holds the Railway and HCP tokens for the project layer, plus the variables `TF_CLOUD_ORGANIZATION` and `RAILWAY_WORKSPACE_ID`. `subtree-sync` holds `SUBTREE_SYNC_TOKEN` (contents write on the mirror repos only). Optional variable `OTEL_EXPORTER_OTLP_ENDPOINT` per environment enables trace export.
