# Architecture

The full architecture document, execution plan and pitch deck are published as Claude artifacts for the team:

- Architecture: https://claude.ai/artifact/Hje8YdHV3njx2TXgywGS1D
- Execution plan: https://claude.ai/artifact/HxXS4MGBucVm5BYuY2zMSM
- Pitch deck: https://claude.ai/artifact/Pz9GdCothnDgwBEFVqWmae

When this repo's ADRs and the published document disagree, the ADRs win.

## One-screen summary

```
channels ──REST──▶ apps/gateway (TS) ──HTTP+traceparent──▶ services/agents (Python)
partner agents ─A2A─▶      │                                  │ LangGraph orchestrator
                           │ SSE ◀── case events ─────────────│  classify → open_tickets → route
                           │                                  │  → specialist → assess
Jira / ServiceNow ─webhooks─┘                                 │  → resolve | await_customer | escalate
                                                              ├─▶ TicketPort: Jira, ServiceNow
                                                              └─▶ CaseStore: Postgres (RLS per tenant)
all processes ──OTLP──▶ otel-collector ──▶ traces / metrics / logs
```

Key decisions: see `docs/adr/`.
