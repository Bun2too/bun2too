# 0002: One case state machine, status derived from events

- Status: accepted
- Date: 2026-11-16

## Context

Status is touched by agents, operators (via ticket webhooks), customers (replies) and timers (SLA). Scattered status writes produce impossible states and lose the audit trail customers and operators need.

## Decision

`relay_agents.case_machine` holds the only transition table. Every change is a `CaseEvent` appended to the store; current status is the latest accepted transition. Illegal transitions raise `IllegalTransition`.

## Consequences

Every writer goes through one function, which makes tracking and replay trivial. Adding a status means editing one table and its tests.
