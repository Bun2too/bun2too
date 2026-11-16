# 0006: Native structured output instead of forced tool calls

- Status: accepted
- Date: 2026-11-16

## Context

Current Claude models (Opus 5.5, Sonnet 5.5) return HTTP 400 for forced `tool_choice` (`any` or a named tool). LangChain's default `with_structured_output` strategy for some providers forces a tool call.

## Decision

Classification and specialist outputs use `with_structured_output(..., method="json_schema")` and LangChain agents use `ProviderStrategy` for `response_format`. Both use the provider's native structured output.

## Consequences

Structured output depends on provider support for JSON schema; providers without it need an adapter in `llm.py`.
