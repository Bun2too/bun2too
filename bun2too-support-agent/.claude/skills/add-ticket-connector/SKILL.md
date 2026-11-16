---

name: add-ticket-connector
description: Add a new system of record behind TicketPort (e.g. Zendesk, Freshservice, Salesforce Service Cloud) for Relay. Use when a tenant needs tickets somewhere other than Jira or ServiceNow.
---

# Add a ticket connector

1. Read `docs/adr/0003-idempotent-ticket-writes.md`. The connector must find by correlation key before it creates.
2. Create `services/agents/src/relay_agents/connectors/<system>.py` implementing `TicketPort` (`ensure_ticket`, `add_note`, `resolve`). Take an `httpx.AsyncClient` in the constructor so tests can pass `httpx.MockTransport`.
3. Store the correlation key in a field the system can search exactly. Document which field in the module docstring with a link to the vendor's API reference.
4. Tests in `tests/test_connectors.py` using `httpx.MockTransport`: calling `ensure_ticket` twice issues one create; a 5xx raises `TicketWriteError`; notes and resolve send the documented payload.
5. Add the system to `TicketSystem` in contracts (both languages) and to the tenant config schema with its field map.
6. Never put credentials in tenant YAML; read them from env names the YAML references (`token_env: ZENDESK_TOKEN`).
