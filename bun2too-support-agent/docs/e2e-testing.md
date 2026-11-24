# End-to-end testing

This guide is for a person or a test agent proving that Relay works in a deployed environment. It covers four levels:

1. **API**: drive the gateway directly.
2. **Tickets**: confirm Relay's Jira issue and ServiceNow record.
3. **Website**: open an inquiry on the bun2too preview site and follow it to tickets.
4. **Report**: what evidence to keep.

The API itself is described in [api.md](api.md) and `GET /openapi.json`.

## Which environment

| Env | Gateway                                   | What it proves                                                                                                                                                      |
| --- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| qa  | https://bun2too-support-qa.up.railway.app | The real flow: Claude classifies and answers through Cloudflare AI Gateway, and real tickets land in the **sandbox** Jira project and ServiceNow developer instance |

qa is the only deployed environment before prod ([ADR 0008](adr/0008-qa-only-pre-prod.md)). For the offline behaviour (keyword classifier, fake tickets), run the stack locally with `RELAY_OFFLINE=1 pnpm dev`, using `RELAY_GATEWAY=http://localhost:8787` and the default key `dev-bun2too-key`. Never run these journeys against prod: they create tickets.

## Before you start

- `curl` and `jq`.
- A **tenant key** for the environment. Ask the owner, who sends it through a secret store, never chat. Every deploy's own journey uses `SMOKE_TENANT_KEY`, a GitHub environment secret you cannot read; use a key issued for testing.
- For qa ticket checks, view access to the sandbox Jira project and the ServiceNow developer instance. Wake the developer instance first: it sleeps when idle, and ticket writes fail while it sleeps.

```sh
export RELAY_GATEWAY=https://bun2too-support-qa.up.railway.app   # or http://localhost:8787 for a local offline run
export RELAY_TENANT_KEY=…                                         # from your secret store; never echo it
cd bun2too-support-agent
```

## Level 1: API journeys

Start with the read-only checks. They create nothing.

```sh
scripts/verify/smoke.sh "$RELAY_GATEWAY"                 # health, agent card, 401 without a key
curl -sS "$RELAY_GATEWAY/openapi.json" | jq '.info.title, (.paths|keys)'
```

Then run the journeys. Each one prints `case <id> -> <status>` and the event log, and saves the evidence under `.verify/<timestamp>/` (`intake.json`, `case.json`, `events.json`, `trace_id.txt`).

| #   | Journey          | Command                                                                                                                                                                                      | Expected (local, offline)                                             | Expected (qa, live)                                                                                 |
| --- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| 1   | Knowledge answer | `scripts/verify/intake.sh "How do I send a private inquiry?"`                                                                                                                                | `resolved`, citation `kb-private-inquiry`, two fake tickets           | `resolved` with an answer drawn from the knowledge seed, one Jira issue and one ServiceNow incident |
| 2   | Privacy          | `scripts/verify/intake.sh "Please delete all my personal data"`                                                                                                                              | `escalated` (policy: privacy always escalates)                        | `escalated`. Both tickets carry the handoff summary                                                 |
| 3   | No answer known  | `scripts/verify/intake.sh "My SSO login fails with error 4711 since today"`                                                                                                                  | `escalated` (low confidence: no knowledge article matched)            | `escalated`, or `awaiting_customer` with a `pendingQuestion` (go to 4)                              |
| 4   | Customer reply   | `curl -sS -X POST "$RELAY_GATEWAY/v1/cases/<id>/messages" -H "x-api-key: $RELAY_TENANT_KEY" -H 'content-type: application/json' -d '{"message":"…answer…"}'`, then poll `GET /v1/cases/<id>` | `409 not_awaiting_customer` (offline never asks)                      | `202`, then the same case settles again. No new tickets; a note is added to both                    |
| 5   | Idempotency      | `RELAY_IDEMPOTENCY_KEY=e2e-fixed-1 scripts/verify/intake.sh "How long are inquiries kept?"`, twice                                                                                           | Same `caseId` both times. The second call returns `200 created:false` | Same, and still one Jira issue and one ServiceNow record                                            |
| 6   | A2A              | `scripts/verify/a2a.sh "The checkout webhook returns 401"`                                                                                                                                   | Task `completed` or `working`, `relayStatus` settled                  | Same, with real ticket links in `metadata.tickets`                                                  |

To watch the agents step by step, stream the events:

```sh
curl -sSN "$RELAY_GATEWAY/v1/cases/<id>/events" -H "x-api-key: $RELAY_TENANT_KEY"
```

A healthy run moves through `received → triaged → ticketed → in_progress → <settled>`. The `ticketed` event's `data.tickets` lists both keys. If `data.pending` is not empty, one ticket system failed; see [Troubleshooting](#troubleshooting).

### Find the case's trace (qa)

Every case is one trace in LangSmith ([ADR 0009](adr/0009-langsmith-tracing.md)): the agents' HTTP request, `relay.case.run`, the LangGraph run, each node, each model call and each outgoing HTTP call. Open the agent `bun2too-support-agent`, environment **staging**, then:

- search by the `traceId` from the intake response (also written in both tickets as `Trace:`), or
- filter by metadata `thread_id = <caseId>` to see the intake and every reply of that case together.

A failed run shows as an errored trace, with the exception on the failing span. Inputs and outputs are hidden unless the environment allows them, so a trace shows structure, timing, model, tokens and errors, not customer text. If a qa case has no trace a minute after it settled, check the trace settings in [runtime secrets](runtime-secrets.md#trace-settings-github-environment-variables-not-secrets).

## Level 2: confirm the tickets (qa)

Every Relay ticket is keyed by the case: the **correlation key** is `relay-<tenant>-<caseId>`, for example `relay-bun2too-3f2a…`. Writes are idempotent on that key, so a retry never duplicates a ticket.

| System     | Where                                                                                                                                                                                                                               | Find it                                                                                                       | Expect                                                                                                                                              |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Jira       | The site in qa's `BUN2TOO_JIRA_BASE_URL`, project `BUN` (from [`tenants/bun2too.yaml`](../tenants/bun2too.yaml)). Relay's issues sit on the same board as engineering work; filter them with JQL `project = BUN AND labels = relay` | Open the link in `case.tickets[]`, or use JQL `labels = "relay-bun2too-<caseId>"`                             | One Task labelled `relay` and with the correlation key. Priority comes from severity. Comments track the case; a resolved case gets a final comment |
| ServiceNow | The developer instance in qa's `BUN2TOO_SNOW_INSTANCE_URL`, table `incident`                                                                                                                                                        | Open the link in `case.tickets[]`, or the incident list filtered by `correlation_id = relay-bun2too-<caseId>` | One incident. Work notes track the case; a resolved case is closed with the tenant's `resolve_fields`                                               |

Check both for every journey. If either system has more than one ticket for a correlation key, that is a bug.

## Level 3: the website (bun2too preview)

**Status:** the website does not send inquiries to Relay yet. Today, **Send a private inquiry** on the [preview site](https://deploy-preview-1--bun2too.netlify.app/) does three things: it saves the inquiry in Netlify Blobs, emails the management inbox through SES, and returns a reference. It opens no ticket ([website docs/support.md](../../bun2too-website/docs/support.md)).

The integration is tracked in the Jira project BUN and assigned to Codex. Once it lands, the website's server forwards each saved inquiry to Relay qa as follows, and this level becomes runnable:

- `POST /v1/intake` with channel `web_widget`.
- `Idempotency-Key` is `bun2too-inquiry-<reference>`.
- The visitor's topic is the `subject`.
- The reference goes in `metadata.reference`. Relay validates it but does not store it yet, so the website keeps the reference → `caseId` mapping on its own inquiry record.
- The tenant key stays in the site's server-side environment.

Steps (person or browser agent):

1. Open the preview site and select **Let's connect → Send a private inquiry**.
2. Fill it in with a test identity you control. Use one message per journey above, for example "How do I send a private inquiry?" for an auto-answer, or "Please delete all my personal data" for an escalation. Give consent, complete the CAPTCHA and submit.
3. Note the **reference** the dialog shows. The site's response also carries the Relay `caseId` (or a status line in the dialog, depending on the website ticket's design).
4. Follow the case with `GET $RELAY_GATEWAY/v1/cases/<caseId>`, or use the event stream above. It should settle as in Level 1.
5. Confirm the tickets as in Level 2. The Jira issue and ServiceNow incident should name the same case. Confirm the link to the website through the inquiry record in Netlify Blobs, which holds the `caseId` Relay returned. Relay itself does not return the website reference.
6. Submit the same form again with the browser's back and resubmit, or retry within the visitor session. You should get the same reference, the same case and no new tickets.
7. Check what the customer sees.
   - **resolved**: the answer, if the website ticket shows it.
   - **escalated**: the "a specialist will follow up" text.
   - **awaiting_customer**: the question and a reply box, if built. Otherwise the reply arrives by email from the team.

## Level 4: what to report

For each journey, record the following, without keys, customer text from real people, or provider responses:

- Environment, gateway URL and git SHA. `deploy-support` writes the SHA to its run summary.
- `caseId`, `traceId`, the final status and the event list, which `scripts/verify/intake.sh` prints.
- The Jira key and ServiceNow number, and whether each was found exactly once.
- For the website: the inquiry reference and a screenshot of the confirmation.
- Anything that could not run, marked **inconclusive** and why (root rule 4).

## Troubleshooting

| Symptom                                                         | Meaning and next step                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `401 unauthorized`                                              | The key isn't in this environment's `RELAY_TENANT_KEYS`. Keys differ per environment                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `503 agents_unavailable`                                        | The agents service is down or restarting. Check `/healthz`, then the Railway agents service. Retry with the same Idempotency-Key                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Event `run failed` with `error: APIStatusError` and a `status`  | The model call was refused upstream.<br>**401/403:** `CF_AIG_TOKEN`, or the Authenticated Gateway setting.<br>**402:** the gateway applied no stored Anthropic key (log shows `byok: null`, `payment_defaulted`): check the key exists under the alias `claude` ([runtime secrets](runtime-secrets.md#cf_aig_-cloudflare-ai-gateway), step 4). Otherwise, billing on the Anthropic workspace.<br>**404:** wrong `CF_AIG_ACCOUNT_ID`/`CF_AIG_GATEWAY_ID`, or a model ID the account cannot use.<br>**429:** a rate or spend limit. Check the Cloudflare AI Gateway logs for that time ([runtime secrets](runtime-secrets.md#cf_aig_-cloudflare-ai-gateway)) |
| `ticketed` event with `pending: ["servicenow"]` or a Jira entry | That system rejected the write. Wake the ServiceNow developer instance, check the credentials and that the Relay account can create Tasks in project `BUN`. Then reply to or resubmit the case: writes converge on the correlation key                                                                                                                                                                                                                                                                                                                                                                                                                     |
| The case stays at `received`                                    | The background run never started or crashed before its first step. Check the agents service deploy logs in Railway, and copy only the exception class into anything public                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |

## Known gaps that block the full e2e

| Gap                                                                                                                  | Owner and fix                                                                                                                                                                              |
| -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| qa's live intake fails with `APIStatusError` (2026-11-22)                                                            | The next qa deploy prints the HTTP status (PR #32). The owner then fixes the Cloudflare or Anthropic setting that status points to                                                         |
| The website does not forward inquiries to Relay                                                                      | Codex, through the BUN Jira tickets                                                                                                                                                        |
| Relay files into the `BUN` project (owner's choice, 2026-11-22), so its issues share the board with engineering work | Owner: give the Relay account **Browse projects**, **Create issues** and **Add comments** in `BUN` ([runtime-secrets.md](runtime-secrets.md)). Filter Relay's issues with `labels = relay` |
| A preview-site key for qa                                                                                            | Owner: add `<key>:bun2too` to qa's `RELAY_TENANT_KEYS` and the same key to the website's preview-context Netlify environment                                                               |
