# Relay

White-label, multi-agent support intake. A channel (website widget, retail system, marketplace, partner agent) hands Relay a customer problem over **REST** or **A2A**. Relay opens a tracked **case**, raises one **Jira** issue and one **ServiceNow** record, and sends a **specialist** agent to resolve it, escalating to people only when policy or confidence requires it. `bun2too` is the demo tenant.

- Architecture: https://claude.ai/artifact/Hje8YdHV3njx2TXgywGS1D
- Execution plan: https://claude.ai/artifact/HxXS4MGBucVm5BYuY2zMSM
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

Offline mode replaces only external systems (model calls, Jira, ServiceNow) with deterministic stand-ins. To use real models, unset `RELAY_OFFLINE` and set `ANTHROPIC_API_KEY`; to use real ticket systems, set the env vars named in `tenants/bun2too.yaml`.

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
| `infra/`             | docker-compose, OTel Collector, Terraform                                                                     |

## How work gets done here

This repo is an agentic application factory. Agents implement, review, rework and autofix; people approve specs and merge finished PRs. Start with [AGENTS.md](AGENTS.md), then [docs/factory/README.md](docs/factory/README.md).

It builds on two open-source skill sets, enabled as plugins in `.claude/settings.json`:

- Matt Pocock's [skills](https://github.com/mattpocock/skills): grilling, `to-spec`, `to-tickets`, `tdd`, two-axis `code-review`, `pr`, and the software-factory vocabulary.
- Lauren Tan's [pstack](https://github.com/cursor/plugins/tree/main/pstack): named engineering principles, `poteto-mode` playbooks, verification skills, `interrogate`, `no-comments`.

### One-time repository setup (a person must do this)

1. `git init`, push to GitHub, and protect `main` (required checks: `ci`; require one human approval).
2. Add secrets: `ANTHROPIC_API_KEY`, and `FACTORY_TOKEN` (a GitHub App or fine-grained token with contents, pull-requests and issues write; not workflows).
3. Create the labels in `docs/agents/triage-labels.md` (`gh label create ...`).
4. Install the Claude GitHub app on the repo so `anthropics/claude-code-action` can comment.
5. `pnpm exec lefthook install` for local pre-commit hooks.
