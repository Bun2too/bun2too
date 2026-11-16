# 0004: OpenTelemetry with GenAI semantic conventions

- Status: accepted
- Date: 2026-11-16

## Context

Tenants run different observability vendors. Agent runs need traces that span TypeScript and Python and show model, tokens and cost per step.

## Decision

All processes export OTLP to an OpenTelemetry Collector. Graph nodes and LLM calls emit spans with `gen_ai.*` attributes (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`) plus `relay.case_id` and `relay.tenant`. The trace ID is stored on the case and written into both tickets.

## Consequences

Vendor choice moves to collector config. GenAI conventions are still evolving; attribute names are centralised in `relay_agents.telemetry` so a rename is one edit.
