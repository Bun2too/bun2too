# Relay: agent guide

Relay is a white-label, multi-agent support intake platform. Channels hand Relay a customer problem over REST or A2A; Relay opens a **case**, raises one Jira issue and one ServiceNow record, and sends **specialists** to resolve it or **escalate** it. `bun2too` is the demo **tenant**. Read [GLOSSARY.md](GLOSSARY.md) before naming anything; use its terms and avoid the words it lists under _Avoid_.

## Map

| Path                 | Language                       | Owns                                                              |
| -------------------- | ------------------------------ | ----------------------------------------------------------------- |
| `apps/gateway`       | TypeScript (Hono)              | REST `/v1/*`, A2A `/a2a` + agent card, SSE, webhooks, tenant auth |
| `apps/widget`        | TypeScript                     | `<relay-support>` embeddable web component                        |
| `packages/contracts` | TypeScript (Zod)               | Wire contracts. Source of truth; exports JSON Schema to `schema/` |
| `packages/telemetry` | TypeScript                     | OpenTelemetry bootstrap for every Node process                    |
| `services/agents`    | Python (LangGraph + LangChain) | Orchestrator graph, specialists, case store, ticket connectors    |
| `tenants/`           | YAML                           | White-label tenant configs. Data, never code branches             |
| `evals/`             | JSONL                          | Golden intakes and expected routing                               |
| `docs/adr/`          | Markdown                       | Decisions. Read the ADRs in the area you touch                    |

Architecture and plan (published for the team): see [docs/architecture.md](docs/architecture.md).

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
7. **Contracts change in one place.** Edit `packages/contracts/src`, run `pnpm contracts:export`, then update `relay_agents/contracts.py`. The `contract drift` check fails until both sides agree.
8. **Trace everything.** New graph nodes use `@traced_node`; new HTTP routes get spans from the telemetry bootstrap. Never log raw customer text; log through `redact()`.
9. **Models via config.** Get models from `relay_agents.llm.chat_model(role, tenant)`. Never hard-code a model ID outside `tenants/*.yaml` and `llm.py` defaults. Structured output uses `method="json_schema"` (forced tool choice returns a 400 on current Claude models).
10. **Deep modules.** Prefer a small interface hiding real work over many thin layers. Ports (`TicketPort`, `CaseStore`, `Classifier`, `Specialist`) are the seams. Tests live at the seams.
11. **No narration comments.** Code says what; names say why. Keep comments only for license headers, public API contracts, and constraints forced by an external system we cannot change (link the doc).
12. **Smallest change that solves it.** Delete before you add. No speculative parameters, flags, or abstractions the ticket did not ask for.

Full standards with examples: [CODING_STANDARDS.md](CODING_STANDARDS.md). Every rule above is paired with what enforces it in [docs/factory/enforcement.md](docs/factory/enforcement.md); when you find yourself repeating advice, add an enforcer there, not more prose here.

## Workflow (the factory)

Work moves through tasks, triggers and runs as defined in [docs/factory/README.md](docs/factory/README.md). In short:

1. **Align.** Grill the requester (`/grill-with-docs`) until the design tree is resolved; update `GLOSSARY.md` and write an ADR for any hard-to-reverse decision.
2. **Spec, then tickets.** `/to-spec` then `/to-tickets`: thin tracer-bullet tickets with blocking edges.
3. **Implement test-first.** `/tdd` at pre-agreed seams, one vertical slice at a time.
4. **Review on two axes.** `/code-review` runs Standards and Spec reviewers in separate fresh contexts. Do not merge their findings.
5. **Rework, capped.** Fix only what the review named. Three failed review rounds ends the loop with the `ready-for-human` label.
6. **Open the PR** following `/pr`: smallest visual summary, before/after evidence, merge-danger call.

A run never waits for a human. It finishes, and the human's later label or comment starts a new run.

## Prove it works

"It compiles" is not evidence. Use `.claude/skills/verify-relay/SKILL.md` to launch the stack, drive the real API, and capture evidence (response bodies, case event log, trace ID). Put the commands and outputs in the PR body. If a check could not run, say **inconclusive** and why.

## Principles to cite

When a principle changes a decision, name it in your reply or PR with the decision it changed (pstack convention): Laziness Protocol, Boundary Discipline, Type System Discipline, Model the Domain, Make Operations Idempotent, Prove It Works, Fix Root Causes, Test Behavior Not Implementation, Encode Lessons in Structure, Never Block on the Human.

## Safety

- Never commit secrets. `.env*` is ignored except `.env.example`.
- Never call live Jira, ServiceNow, CIAM or LLM endpoints from tests. Run with `RELAY_OFFLINE=1` wiring: the keyword classifier, `KnowledgeLookupSpecialist` and the fakes in `relay_agents.connectors.fakes`.
- Never push to `main`, force-push, or change CI permissions from an agent run.
- Changes under `.claude/`, `.cursor/`, `.github/`, `AGENTS.md` and `docs/factory/` change the factory itself and always need human review.

## Agent skills

### Issue tracker

GitHub Issues on this repo, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
