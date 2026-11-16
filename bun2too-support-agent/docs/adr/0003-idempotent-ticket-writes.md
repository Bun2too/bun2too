# 0003: Idempotent ticket writes keyed by correlation key

- Status: accepted
- Date: 2026-11-16

## Context

Each case opens one Jira issue and one ServiceNow record. Network failures and process restarts between "create" and "record the reference" are normal, and duplicates in a tenant's ServiceNow are expensive to clean up.

## Decision

`TicketPort.ensure_ticket` searches by correlation key `relay-{tenant}-{caseId}` (Jira label, ServiceNow `correlation_id`) before creating. Phase 2 adds a transactional outbox so the intent to write is stored atomically with the case event.

## Consequences

One extra search request per create. Retries are always safe.
