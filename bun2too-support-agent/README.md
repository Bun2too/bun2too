# Relay

White-label, multi-agent support intake. A channel (website widget, retail system, marketplace, partner agent) hands Relay a customer problem over **REST** or **A2A**. Relay opens a tracked **case**, raises one **Jira** issue and one **ServiceNow** record, and sends a **specialist** agent to resolve it, escalating to people only when policy or confidence requires it. `bun2too` is the demo tenant.

- Architecture: https://claude.ai/artifact/Hje8YdHV3njx2TXgywGS1D
- API for clients and agents: [docs/api.md](docs/api.md). OpenAPI 3.1 at `GET /openapi.json` on every gateway ([repo copy](packages/contracts/schema/openapi.json))
- Testing a deployed environment end to end, including tickets and the website: [docs/e2e-testing.md](docs/e2e-testing.md)
- Execution plan (three weeks): https://claude.ai/artifact/HxXS4MGBucVm5BYuY2zMSM
- Pitch deck: https://claude.ai/artifact/Pz9GdCothnDgwBEFVqWmae

## Quick start (offline, no keys needed)

Requires Node 24+, pnpm 10, [uv](https://docs.astral.sh/uv/), and optionally Docker for traces.

```sh
pnpm install
uv sync --directory services/agents
pnpm contracts:export
pnpm check                         # every CI gate
pnpm stack:up                      # optional: postgres, otel-collector, jaeger (http://localhost:16686)
RELAY_OFFLINE=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 pnpm dev
scripts/verify/intake.sh "How do I send a private inquiry?"
```

Offline mode replaces only external systems (model calls, Jira, ServiceNow) with deterministic stand-ins. To use real models, unset `RELAY_OFFLINE` and set `ANTHROPIC_API_KEY` (add the `CF_AIG_*` keys to route through Cloudflare AI Gateway, as qa and prod do; see [ADR 0007](docs/adr/0007-cloudflare-ai-gateway.md)); to use real ticket systems, set the env vars named in `tenants/bun2too.yaml`.

## Layout

| Path                 | What                                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------------------- |
| `apps/gateway`       | TypeScript (Hono): REST `/v1/*`, A2A `/a2a` and `/.well-known/agent-card.json`, SSE case events               |
| `apps/widget`        | `<relay-support>` embeddable web component                                                                    |
| `packages/contracts` | Zod wire contracts, exported to JSON Schema for Python                                                        |
| `packages/telemetry` | OpenTelemetry bootstrap for Node                                                                              |
| `services/agents`    | Python (LangGraph + LangChain): orchestrator, specialists, policy, case store, Jira and ServiceNow connectors |
| `tenants/`           | White-label tenant configs                                                                                    |
| `evals/`             | Golden intakes; `pnpm eval`                                                                                   |
| `infra/`             | docker-compose, OTel Collector; Terraform for Railway (POC) and GCP Cloud Run (GA candidate)                  |
| `scripts/deploy/`    | Railway upload and deploy wait, volume check (used by CI only)                                                |

## Deployment

| Environment | Where                                             | When                                                                                                       |
| ----------- | ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| qa          | Railway `bun2too-support-qa` / `qa`               | every merge to `main` (live; the only pre-prod environment, [ADR 0008](docs/adr/0008-qa-only-pre-prod.md)) |
| prod        | Railway `bun2too-support-prod` / `prod`           | after qa, with a person's approval                                                                         |
| GA          | Google Cloud Run (`infra/terraform/gcp-cloudrun`) | after the POC                                                                                              |

Pipeline: root `.github/workflows/deploy-support.yml`. Runtime secrets: [docs/runtime-secrets.md](docs/runtime-secrets.md). Terraform: [infra/terraform/railway/README.md](infra/terraform/railway/README.md). Release and rollback: [../docs/sop/environments-and-release.md](../docs/sop/environments-and-release.md).

## How work gets done here

This product is a subtree of the Bun2too monorepo, and is built by the shared agent factory there. Start with the root [AGENTS.md](../AGENTS.md) and [docs/sdlc.md](../docs/sdlc.md), then this folder's [AGENTS.md](AGENTS.md). The lifecycle follows Addy Osmani's [agent-skills](https://github.com/addyosmani/agent-skills), with Matt Pocock's [skills](https://github.com/mattpocock/skills) used for the GitHub Issues bridge and grilling.
