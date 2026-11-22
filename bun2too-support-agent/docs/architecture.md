# Architecture

The full architecture document, execution plan and pitch deck are published as Claude artifacts for the team:

- Architecture: https://claude.ai/artifact/Hje8YdHV3njx2TXgywGS1D
- Execution plan (three weeks): https://claude.ai/artifact/HxXS4MGBucVm5BYuY2zMSM
- Pitch deck: https://claude.ai/artifact/Pz9GdCothnDgwBEFVqWmae

When this repo's ADRs and the published document disagree, the ADRs win.

## One-screen summary

```
channels ──REST──▶ apps/gateway (TS) ──HTTP+traceparent──▶ services/agents (Python)
partner agents ─A2A─▶      │                                  │ LangGraph orchestrator
                           │ SSE ◀── case events ─────────────│  classify → open_tickets → route
                           │                                  │  → specialist → assess
Jira / ServiceNow ─webhooks─┘                                 │  → resolve | await_customer | escalate
                                                              ├─▶ Cloudflare AI Gateway ──▶ Anthropic (qa, prod)
                                                              ├─▶ TicketPort: Jira, ServiceNow
                                                              └─▶ CaseStore: Postgres (RLS per tenant)
all processes ──OTLP──▶ otel-collector ──▶ traces / metrics / logs
```

Runtime: one Railway project per environment (`bun2too-support-qa`, `-prod`; no dev, see [ADR 0008](adr/0008-qa-only-pre-prod.md)), each running `gateway` (public), `agents` (private network) and `postgres` (its own volume). GA candidate: Google Cloud Run. See the root `docs/adr/0004-railway-poc-gcp-ga.md`. Model calls go through Cloudflare AI Gateway, one gateway per environment ([ADR 0007](adr/0007-cloudflare-ai-gateway.md)).

Key decisions: see `docs/adr/`.
