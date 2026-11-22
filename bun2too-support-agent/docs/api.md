# Relay API

Relay takes a customer problem and returns a tracked support **case**. Each case gets one Jira issue and one ServiceNow record. Relay's specialists then resolve the case, ask the customer one question, or escalate it to a person.

- **Machine-readable spec:** every gateway serves its OpenAPI 3.1 document at `GET /openapi.json`, with `servers` set to that gateway's URL. The repository copy is [`packages/contracts/schema/openapi.json`](../packages/contracts/schema/openapi.json).
  - It is generated from the Zod contracts in [`packages/contracts/src`](../packages/contracts/src) by `pnpm contracts:export`.
  - CI fails if the copy drifts from the code.
  - Import it into Postman, Insomnia or an SDK generator, or hand it to an agent as a tool definition.
- **Agents:** the same flow is available over [A2A](https://a2a-protocol.org) 0.3.0. The agent card is at `GET /.well-known/agent-card.json`, and the JSON-RPC endpoint is `POST /a2a`.

| Environment | Gateway                                      | Mode                                                                                       |
| ----------- | -------------------------------------------- | ------------------------------------------------------------------------------------------ |
| dev         | `https://bun2too-support-dev.up.railway.app` | Offline. A keyword classifier, knowledge-base answers and fake tickets (`*.invalid` links) |
| qa          | `https://bun2too-support-qa.up.railway.app`  | Live. Claude through Cloudflare AI Gateway, with real Jira and ServiceNow sandboxes        |
| prod        | Not deployed yet                             | Live                                                                                       |

## Authentication

Every `/v1/*` and `/a2a` call needs a **tenant key**. Send it as `x-api-key: <key>` or as `Authorization: Bearer <key>`. A missing or unknown key gets `401 {"error":"unauthorized"}`.

The key decides the tenant, so a caller cannot read another tenant's cases.

Keys are issued by the Relay operator ([runtime secrets](runtime-secrets.md#relay_tenant_keys)), one per caller and per environment.

**Keep keys server-side.** The gateway sends no CORS headers, so a browser cannot call it directly. Call it from your server, for example a Next.js route handler or a Netlify function, and keep the key in that server's secret store.

## The flow

```text
POST /v1/intake ──► 202 { caseId, status: "received" }
        │
        ▼  (agents run in the background, usually seconds; live mode up to a minute)
received → triaged → ticketed → in_progress → resolved | awaiting_customer | escalated
                                                        (rejected if the request is refused)
        │
        ├─ GET /v1/cases/{id}            poll until the status settles
        ├─ GET /v1/cases/{id}/events     or stream every step (SSE)
        └─ POST /v1/cases/{id}/messages  answer the question when awaiting_customer
```

A case is **settled** at `resolved`, `awaiting_customer`, `escalated` or `rejected`. In a settled case:

- `resolution.message` holds the customer-facing answer or handoff note.
- `pendingQuestion` holds the one question to show the customer (only at `awaiting_customer`).
- `tickets[]` holds the Jira and ServiceNow keys and links.

### Open a case

```sh
curl -sS -X POST "$RELAY/v1/intake" \
  -H "x-api-key: $RELAY_KEY" \
  -H "Idempotency-Key: website-inquiry-$REFERENCE" \
  -H 'content-type: application/json' \
  -d '{
        "channel": "web_widget",
        "subject": "Cannot sign in",
        "message": "I reset my password but the login page still says invalid credentials.",
        "customer": { "email": "ada@example.com", "name": "Ada", "locale": "en" },
        "metadata": { "source": "bun2too-website", "reference": "INQ-123" }
      }'
# 202 {"caseId":"…","status":"received","traceId":"…","created":true}
```

| Field      | Required | Rules                                                                                         |
| ---------- | -------- | --------------------------------------------------------------------------------------------- |
| `channel`  | yes      | `web_widget`, `a2a`, `email`, `marketplace` or `retail`                                       |
| `message`  | yes      | 1–8000 characters after trimming                                                              |
| `subject`  | no       | 1–300 characters                                                                              |
| `customer` | no       | Any of `id`, `email`, `name`, `locale`. Self-reported, so never treat it as proof of identity |
| `metadata` | no       | String map. Keys up to 64 characters, values up to 500. Use it for your own references        |

Unknown fields are rejected with `422 invalid_intake` and an `issues` list.

**Idempotency.** `Idempotency-Key` is required, at most 200 characters, and scoped to the tenant.

- Derive it from your own submission ID (the website's inquiry reference, an email Message-ID).
- Retrying with the same key returns the same case with `200` and `created: false`. It never opens a second case or a second set of tickets.
- Retry a `503 agents_unavailable` with the same key.

### Follow a case

```sh
curl -sS "$RELAY/v1/cases/$CASE" -H "x-api-key: $RELAY_KEY"
```

Or stream it. Each `case_event` message carries a `CaseEvent` (`seq`, `status`, `actor`, `reason`, `data`). The stream closes once the case settles, or after 120 seconds.

```sh
curl -sSN "$RELAY/v1/cases/$CASE/events" -H "x-api-key: $RELAY_KEY"
```

`event.data` explains each step:

- `tickets` on the `ticketed` event.
- The policy rule on an escalation.
- On a failed run, `reason: "run failed"` with `error` (an exception class) and, for an upstream HTTP failure, `status`.

### Answer a question

Only while the case is `awaiting_customer`. Any other status returns `409 not_awaiting_customer`.

```sh
curl -sS -X POST "$RELAY/v1/cases/$CASE/messages" -H "x-api-key: $RELAY_KEY" \
  -H 'content-type: application/json' -d '{"message":"It is the EU workspace, user ada@example.com"}'
# 202 with the case. Keep polling, because the agents resume on the same tickets.
```

## Errors

Every error body is `{"error": "<code>"}`, plus `issues` on a 422.

| HTTP | `error`                           | Meaning                                                     |
| ---- | --------------------------------- | ----------------------------------------------------------- |
| 400  | `idempotency_key_required`        | Header missing or longer than 200 characters                |
| 401  | `unauthorized`                    | Missing or unknown tenant key                               |
| 404  | `not_found`                       | No such case for this tenant                                |
| 409  | `not_awaiting_customer`           | Reply sent to a case that is not waiting for one            |
| 422  | `invalid_intake`, `invalid_reply` | Body failed validation                                      |
| 503  | `agents_unavailable`              | The agents service is down or slow. Retry with the same key |
| 500  | `internal`                        | Unexpected. Report the case's `traceId`                     |

## A2A (agents)

Discover the agent at `/.well-known/agent-card.json`, then call `POST /a2a` with JSON-RPC 2.0, using the same tenant key header.

| Method         | Use                                                                                                                           |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `message/send` | Opens a case from the text parts (`messageId` is the idempotency key). With `message.taskId`, it answers that case's question |
| `tasks/get`    | `params.id` is the task (case) ID                                                                                             |

A task's `status.state` follows the case:

| Case status             | Task state       |
| ----------------------- | ---------------- |
| `received`              | `submitted`      |
| `triaged` … `escalated` | `working`        |
| `awaiting_customer`     | `input-required` |
| `resolved`              | `completed`      |
| `rejected`              | `rejected`       |

`metadata.relayStatus`, `metadata.traceId` and `metadata.tickets` carry Relay's own view. Streaming, push notifications and `tasks/cancel` are not supported.

```sh
curl -sS -X POST "$RELAY/a2a" -H "x-api-key: $RELAY_KEY" -H 'content-type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"message/send",
  "params":{"message":{"role":"user","messageId":"m-1","parts":[{"kind":"text","text":"The checkout webhook returns 401"}]}}}'
```

## Changing the API

The contracts in `packages/contracts/src` are the source of truth (product rule 7). After changing them or `openapi.ts`, run `pnpm contracts:export`, then update `relay_agents/contracts.py`. Commit the regenerated `schema/*.json`, including `openapi.json`.
