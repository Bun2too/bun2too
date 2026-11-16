# 0001: TypeScript at the edge, Python for agents

- Status: accepted
- Date: 2026-11-16

## Context

Relay needs an embeddable widget, an HTTP/A2A gateway, and a multi-agent runtime. LangGraph's Python runtime has the most mature checkpointing, interrupts and ecosystem. Widgets and web gateways are most natural in TypeScript, and most tenant web teams already run Node.

## Decision

`apps/gateway` and `apps/widget` are TypeScript. `services/agents` is Python with LangGraph and LangChain. They talk over HTTP with W3C `traceparent` propagation. Wire shapes are defined once in `packages/contracts` (Zod) and exported as JSON Schema; Python mirrors them in Pydantic and a parity test keeps them aligned.

## Consequences

Two toolchains in CI. Contract drift is a real risk, so it is a CI gate, not a convention.
