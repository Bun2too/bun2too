# 0009: Export Relay's traces to LangSmith

- Status: proposed
- Date: 2026-11-24
- Owner decision (2026-11-24): trace the agents with LangSmith, agent ID `bun2too-support-agent`, environment `staging` for qa, endpoint `https://api.smith.langchain.com`.

## Context

ADR 0004 gave every process OpenTelemetry spans, but no deployed environment ever set an exporter, so qa dropped every span. A case could stall or fail with nothing outside Relay's own event log to show it. Its `traceId` was returned to callers and written into both tickets, but it led nowhere.

The agents run on LangGraph and LangChain, which LangSmith traces natively. LangSmith also accepts OTLP, which keeps ADR 0004's vendor-neutral spans. Instrumenting the same calls twice, with the SDK and with OpenTelemetry, would send duplicate or disconnected runs.

Customer text is in every node's state and every prompt. ADR 0007 and AGENTS.md rule 8 keep it out of logs and traces.

## Decision

- **One pipeline.** `setup_telemetry` exports the process's OpenTelemetry spans to `<LANGSMITH_ENDPOINT>/otel/v1/traces`. The agent headers address the export: `x-api-key`, `Langsmith-Agent-Id`, `Langsmith-Agent-Environment` and, when it is set, `X-Tenant-Id`. It also switches LangChain to `LANGSMITH_TRACING_MODE=otel`. LangGraph's node runs and model calls then become spans of the same provider, inside the case's trace, and the SDK sends nothing of its own. An OTLP collector (`OTEL_EXPORTER_OTLP_ENDPOINT`) can receive the same spans alongside.
- **One trace per case.** The HTTP request, `relay.case.run`, the LangGraph run, each node, each model call and each outgoing HTTP call share one trace ID: the `traceId` the API returns and the tickets carry. Every node and `relay.case.run` carry the case ID as LangSmith's `thread_id`, so an intake and its later replies group as one thread. A failed run sets the span's error status. Every exported error is reduced to its class name: LangSmith records a failed run's whole error and traceback as an exception event, and OpenTelemetry writes `Type: message` into the status, and either can carry customer text or a provider's response that hidden payloads do not cover.
- **LangGraph traces the nodes.** The hand-written `@traced_node` spans repeated LangGraph's node runs beside them, so they are removed. Coverage is proved by a test that exports a real case and finds every node it ran in that case's trace.
- **Configuration.** These are set per runtime (see the [tracing matrix](../../../docs/sop/tracing.md)):
  - Non-secret: `LANGSMITH_ENDPOINT`, `LANGSMITH_AGENT_ID`, `LANGSMITH_AGENT_ENVIRONMENT` (`local`, `development`, `staging` or `production`), and optionally `LANGSMITH_WORKSPACE_ID`.
  - Secret: `LANGSMITH_API_KEY`, one key per deployed environment, in `SUPPORT_RUNTIME_SECRETS`.
- **Fail loudly.** Setting one of the key, the agent ID or the environment without the others stops the service at start-up. So do an unknown environment and any project setting (`LANGSMITH_PROJECT`, `LANGCHAIN_PROJECT` or their legacy `_SESSION` names) alongside agent addressing, which LangSmith rejects with 400. The key travels in a header, so `LANGSMITH_ENDPOINT` must be an `https://` URL with no user, password, query or fragment. Plain `http://` is accepted only on loopback, for the local trace probe. A half-configured runtime never runs while silently dropping traces.
- **Payloads stay in by default.** Relay sets `LANGSMITH_HIDE_INPUTS` and `LANGSMITH_HIDE_OUTPUTS` to `true` unless the environment sets them. LangSmith then holds each run's structure, timing, model, token use, errors, case ID and tenant, but no customer text and no answers. An environment shows payloads only when it sets both to `false`. **Owner decision pending:** whether qa, which handles sandbox data only, may show payloads. Prod keeps them hidden.

## Consequences

- Each qa case can be found in LangSmith by its `traceId` or its case ID (thread), with every node, model call and HTTP call in one tree. Errors, latency and token use are visible without reading Relay's database.
- LangSmith becomes a data processor for trace metadata, and for payloads in any environment that opts in. Keys are per environment, so qa's can be revoked alone.
- The gateway (TypeScript) is not instrumented yet. The trace starts at the agents service's HTTP span. Adding the gateway is a follow-up.
- A live service that loses its LangSmith key fails at start-up rather than running untraced. That is deliberate; clear all three settings to turn tracing off.
