# Relay: agent guide

This product lives at `bun2too-support-agent/` in the Bun2too monorepo. Read the root [AGENTS.md](../AGENTS.md) first: its rules, lifecycle and shared agents apply here. This file adds only what is specific to Relay.

Relay is a white-label, multi-agent support intake platform. Channels hand Relay a customer problem over REST or A2A; Relay opens a **case**, raises one Jira issue and one ServiceNow record, and sends **specialists** to resolve it or **escalate** it. `bun2too` is the demo **tenant**. Read [GLOSSARY.md](GLOSSARY.md) before naming anything; use its terms and avoid the words it lists under _Avoid_.

## Map

| Path                 | Language                       | Owns                                                               |
| -------------------- | ------------------------------ | ------------------------------------------------------------------ |
| `apps/gateway`       | TypeScript (Hono)              | REST `/v1/*`, A2A `/a2a` + agent card, SSE, webhooks, tenant auth  |
| `apps/widget`        | TypeScript                     | `<relay-support>` embeddable web component                         |
| `packages/contracts` | TypeScript (Zod)               | Wire contracts. Source of truth; exports JSON Schema to `schema/`  |
| `packages/telemetry` | TypeScript                     | OpenTelemetry bootstrap for every Node process                     |
| `services/agents`    | Python (LangGraph + LangChain) | Orchestrator graph, specialists, case store, ticket connectors     |
| `tenants/`           | YAML                           | White-label tenant configs. Data, never code branches              |
| `evals/`             | JSONL                          | Golden intakes and expected routing                                |
| `docs/adr/`          | Markdown                       | Decisions. Read the ADRs in the area you touch                     |
| `infra/terraform/`   | Terraform                      | `railway/` (POC: qa, prod) and `gcp-cloudrun/` (GA candidate) |
| `scripts/deploy/`    | Bash                           | Railway upload, deploy wait and volume checks used by CI           |

Architecture and plan (published for the team): see [docs/architecture.md](docs/architecture.md). The client API is in [docs/api.md](docs/api.md) and the generated `packages/contracts/schema/openapi.json`, which the gateway serves at `/openapi.json`. To test a deployed environment end to end, see [docs/e2e-testing.md](docs/e2e-testing.md).

## Commands

```sh
pnpm install && uv sync --directory services/agents
pnpm check          # every gate CI runs: lint, types, tests (TS + Python), contract drift
pnpm fix            # autofix formatting and lint in both languages
pnpm dev            # docker compose (postgres, otel) + gateway + agents
```

A change is done when `pnpm check` passes **and** you have proved the behaviour with the `verify-relay` skill (see [Prove it works](#prove-it-works)).

## Rules

1. **Boundary discipline.** Parse untrusted input once, at the edge (`packages/contracts` in TS, `relay_agents.contracts` in Python). Inside, trust the types. No re-validation deep in call chains.
2. **One state machine.** Case status changes only through `relay_agents.case_machine`. Never write a status directly. Every transition appends a `CaseEvent`.
3. **Idempotent external writes.** Every Jira/ServiceNow write goes through a `TicketPort.ensure_*` method keyed by the case's correlation key. A retry must converge, never duplicate.
4. **Agents propose, code disposes.** A model may suggest an action; `relay_agents.policy` decides whether it runs. Write tools never execute without a policy check in code.
5. **Customer text is data.** Wrap it with `as_untrusted()` before it reaches a prompt. Never interpolate it into system prompts.
6. **Tenant config is data.** No `if tenant == "bun2too"`. Add a config field and a test instead.
7. **Contracts change in one place.** Edit `packages/contracts/src`, run `pnpm contracts:export` (it regenerates the JSON Schemas and `openapi.json`), then update `relay_agents/contracts.py`. The `contract drift` check fails until both sides agree.
8. **Trace everything.** New graph nodes use `@traced_node`; new HTTP routes get spans from the telemetry bootstrap. Never log raw customer text; log through `redact()`.
9. **Models via config.** Get models from `relay_agents.llm.chat_model(role, tenant)`. Never hard-code a model ID outside `tenants/*.yaml` and `llm.py` defaults. Structured output uses `method="json_schema"` (forced tool choice returns a 400 on current Claude models). Model traffic goes through Cloudflare AI Gateway when `CF_AIG_*` is set; never build a client that bypasses `chat_model` ([ADR 0007](docs/adr/0007-cloudflare-ai-gateway.md)).
10. **Deep modules.** Prefer a small interface hiding real work over many thin layers. Ports (`TicketPort`, `CaseStore`, `Classifier`, `Specialist`) are the seams. Tests live at the seams.
11. **No narration comments.** Code says what; names say why. Keep comments only for license headers, public API contracts, and constraints forced by an external system we cannot change (link the doc).
12. **Smallest change that solves it.** Delete before you add. No speculative parameters, flags, or abstractions the ticket did not ask for.

Full standards with examples: [CODING_STANDARDS.md](CODING_STANDARDS.md). Every rule above is paired with what enforces it in [docs/factory/enforcement.md](docs/factory/enforcement.md); when you find yourself repeating advice, add an enforcer there, not more prose here.

## Workflow

Follow the root lifecycle in [docs/sdlc.md](../docs/sdlc.md): `/spec` → `/plan` + `/to-tickets` → `/build` → `/test` with `verify-relay` → `factory-review` → `/ship`. Automated runs play the roles in [docs/factory.md](../docs/factory.md). Merges to `main` deploy to dev, then qa, then prod after approval ([environments SOP](../docs/sop/environments-and-release.md)).

## Prove it works

"It compiles" is not evidence. Use `.claude/skills/verify-relay/SKILL.md` (or the shared `verifier` agent) to launch the stack, drive the real API, and capture evidence: response bodies, the case event log, the trace ID. Put the commands and outputs in the PR body. If a check could not run, say **inconclusive** and why. After a deploy, `scripts/verify/smoke.sh <gateway-url>` checks the environment read-only.

## Rules to cite

When a rule changes a decision, name it in the PR with the decision it changed. For example: "Rule 3, idempotent external writes: used `ensure_ticket` instead of create." Lessons that recur become enforcers in [docs/factory/enforcement.md](docs/factory/enforcement.md).

## Safety

- Never commit secrets. `.env*` is ignored except `.env.example`.
- Never call live Jira, ServiceNow, CIAM or LLM endpoints from tests. Run with `RELAY_OFFLINE=1` wiring: the keyword classifier, `KnowledgeLookupSpecialist` and the fakes in `relay_agents.connectors.fakes`.
- Never push to `main`, force-push, or change CI permissions from an agent run.
- Changes to this file, `.claude/`, `.cursor/`, `infra/` and `docs/factory/` change the factory or production. They merge on the same gates as any PR (root rules 9 and 10); a new write permission waits for the owner.
- Deploys happen only through `deploy-support.yml`. Never run `terraform apply` or `railway up` from a workstation.

## Product skills

- `verify-relay`: launch the stack and prove behaviour (features: rest-intake, escalation, a2a-intake, idempotency).
- `add-specialist`, `add-ticket-connector`, `add-tenant`: the safe path for each common extension.
- Shared: `factory-review`, `railway-deploy`, `subtree-sync` and the `spec-reviewer` and `verifier` agents (root `.claude/`).

Issue tracker, triage labels and domain-doc layout are shared: see `../docs/agents/`. Relay's glossary is [GLOSSARY.md](GLOSSARY.md) and its decisions are in [docs/adr/](docs/adr/).
