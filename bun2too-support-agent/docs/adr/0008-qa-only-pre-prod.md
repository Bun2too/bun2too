# 0008: qa is the only environment before prod

- Status: accepted
- Date: 2026-11-22

## Context

The Railway POC ran three environments, each with its own Railway project, HCP Terraform workspace and GitHub environment: dev (offline, with a stand-in model and fake tickets), qa (live, with ticket sandboxes) and prod. The owner wants only one live pre-prod environment, to save cost. dev proved wiring and the API contract, and `pnpm check` and local offline runs (`RELAY_OFFLINE=1 pnpm dev`) already prove the same before a merge.

## Decision

- `deploy-support.yml` deploys every merge to **qa**, then to prod after a person approves in `support-prod`. Manual runs choose qa or prod.
- Terraform accepts only `qa` and `prod`. Deployed environments always run live, and offline mode exists only for local runs and tests.
- The dev resources are removed after this decision merges, never before: the Railway project `bun2too-support-dev`, the HCP workspace `bun2too-support-dev` and the GitHub environment `support-dev` with its secrets.

## Consequences

- A merge reaches a live model and real ticket systems straight away. `pnpm check` (in CI and in the deploy's verify job) is the only gate before qa.
- Each qa deploy's intake journey opens one real case. It therefore creates one Jira issue in project BUN (label `relay`) and one ServiceNow incident, and makes paid model calls.
- A failing qa deploy blocks prod as before.
- Bringing dev back means re-adding it to the workflow and the Terraform validation, and recreating its GitHub environment and HCP workspace. Its old state is not kept.
