---
name: agent-observability
description: Diagnose agent traces, missing telemetry, model routing, measured usage/cost, and operational alert delivery in the CrewAI service.
---

Start with `docs/telemetry-implementation.md`, `docs/model-routing-and-cost-controls.md` and the relevant code: `start.py`, `app/otel.py`, `app/observability.py`, `app/ai_telemetry.py`, `app/langsmith_trace.py`, `app/notifications.py`.

Identify the active instrumentation owner before changing settings: enterprise OTLP, Datadog LLMObs and LangSmith have distinct exporters. An APM export failure does not prove generation failed. Verify SDK endpoint behavior before labeling a hostname invalid. Large traces need attribute/span evidence; increasing a buffer alone is not a root-cause fix.

Use run/task IDs and `model_route_selected`/`llm_call_finished` events to identify the actual model and outcome. Aggregate generation_settings may name the fallback model. Unknown usage/cost stays unknown; cache writes need their own rate. A between-call budget is not an account-level hard spending cap.

Keep prompt capture opt-in and credentials redacted. Record concise evidence and decisions, not claims of private reasoning access. Tests should exercise real serialization or isolated exporters without sending secrets or telemetry. Verify actual notification channel receipts separately from queued records. Do not disable all operational visibility merely to suppress an exporter warning.
