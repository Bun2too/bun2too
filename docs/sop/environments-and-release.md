# SOP: environments and release (support agent)

| Environment | Railway project / environment   | Trigger                                              | Data and integrations                                     | Who approves             |
| ----------- | ------------------------------- | ---------------------------------------------------- | --------------------------------------------------------- | ------------------------ |
| qa          | `bun2too-support-qa` / `qa`     | every merge to `main` that touches the support agent | Live model; Jira project `BUN` (label `relay`) and the ServiceNow developer instance | nobody                   |
| prod        | `bun2too-support-prod` / `prod` | qa smoke and eval pass                               | Live model; production Jira and ServiceNow for the tenant | `support-prod` reviewers |

qa is the only environment before prod; dev was removed on 2026-11-22 to save cost ([ADR 0008](../../bun2too-support-agent/docs/adr/0008-qa-only-pre-prod.md)). `pnpm check` in CI and in the deploy's verify job is the only gate before qa, and local offline runs (`RELAY_OFFLINE=1 pnpm dev`) replace the old offline dev.

Each environment is its own Railway project, named like its HCP Terraform workspace (`bun2too-support-qa`, `-prod`), with one Railway environment of the short name. Each runs the same three services: `gateway` (public), `agents` (private network only) and `postgres` (volume per environment).

## How a release flows

```
merge to main
  └─ deploy-support.yml
       verify (pnpm check on the exact commit)
       └─ qa    terraform apply (bun2too-support-qa) → railway up gateway + agents → smoke + intake journey (one real case and tickets)
          └─ prod  [human approval] → terraform apply → railway up → smoke (read-only, no tickets created)
```

Each environment gets the same commit SHA, recorded as the Railway deployment message. Railway builds each environment from that commit's source with lockfiles and pinned base images. On GCP (GA), the pipeline will build once and promote one immutable image digest instead; see [ADR 0004](../adr/0004-railway-poc-gcp-ga.md).

## Configuration changes

- Each environment's Railway project, services, variables, secrets and domain are applied by Terraform (`infra/terraform/railway`, workspace `bun2too-support-<environment>`) in the same deploy job. So infrastructure and config are promoted qa → prod like code.
- PRs get only credential-free checks in `ci.yml` (fmt, validate, test with mocked providers), because a plan runs PR-controlled Terraform.

## Rollback

1. Actions → `deploy-support` → **Run workflow**. Choose the environment and the last good commit SHA.
2. The run re-applies that commit's config and redeploys its source. Prod still needs approval.
3. If config is not the cause, a faster path is to redeploy the previous deployment in the Railway dashboard. Record it in the incident notes.

## Secrets and variables (per GitHub environment `support-qa`, `support-prod`)

| Name                      | Kind     | Holds                                                                                                                                                                                                                                                                                      |
| ------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `RAILWAY_API_TOKEN`       | secret   | Railway account or workspace token (not a project token)                                                                                                                                                                                                                                   |
| `TF_API_TOKEN`            | secret   | HCP Terraform team token (or a user token) whose team has **Write** access to the project `bun2too-support-app`: it must lock the workspace and read and write state. An organization token or read-only team cannot, and fails as "Error acquiring the state lock: resource not found".   |
| `SUPPORT_RUNTIME_SECRETS` | secret   | JSON map: `RELAY_TENANT_KEYS` (all environments), plus `ANTHROPIC_API_KEY`, the Cloudflare AI Gateway `CF_AIG_*` keys, `BUN2TOO_JIRA_*` and `BUN2TOO_SNOW_*`. What each key is and how to obtain it: [runtime secrets](../../bun2too-support-agent/docs/runtime-secrets.md) |
| `SMOKE_TENANT_KEY`        | secret   | A tenant API key that the smoke journey may use; must be one of the keys in `RELAY_TENANT_KEYS`                                                                                                                                                                                            |
| `TF_CLOUD_ORGANIZATION`   | variable | HCP Terraform organisation                                                                                                                                                                                                                                                                 |
| `TF_WORKSPACE`            | variable | Optional. HCP workspace; defaults to `bun2too-support-<environment>`                                                                                                                                                                                                                       |
| `RAILWAY_WORKSPACE_ID`    | variable | Railway workspace that owns the projects (a repository variable serves both)                                                                                                                                                                                                          |

The `support-prod` environment has required reviewers. `subtree-sync` holds `SUBTREE_SYNC_TOKEN` (contents write on the mirror repos only). Optional variable `OTEL_EXPORTER_OTLP_ENDPOINT` per environment enables trace export.

## Removing dev (once, after ADR 0008 merges)

Do nothing below before the PR that removes dev from `deploy-support.yml` is merged: until then a push could still deploy dev. After it merges, the owner removes the following. Agents don't, because these are outside the repo and can't be undone.

1. Railway: delete the project `bun2too-support-dev`. This removes its services, its Postgres volume and its domain.
2. HCP Terraform: delete the workspace `bun2too-support-dev` in the project `bun2too-support-app`. Its state is not needed, because Terraform no longer accepts `dev`.
3. GitHub: delete the environment `support-dev` and its secrets (Settings → Environments).
4. Cloudflare, Jira and ServiceNow need nothing, because dev never used them.
