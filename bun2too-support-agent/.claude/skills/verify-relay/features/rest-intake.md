# REST intake to auto-resolution

## Sub-features

Validation at the gateway, classification, case creation, Jira and ServiceNow ticket creation, knowledge specialist answer, assessment, resolution.

## How to get to it (user POV)

A channel (the website widget) posts the customer's message to `POST /v1/intake` with a tenant API key and an `Idempotency-Key`.

## Driving it with curl

`scripts/verify/intake.sh "How do I send a private inquiry?" web_widget`

Expected final `case.json`: `status` = `resolved`, `classification.intent` = `knowledge`, `tickets` has `jira` and `servicenow`. `events.json` statuses in order: `received`, `triaged`, `ticketed`, `in_progress`, `resolved`.

## Gotchas

Offline mode's knowledge base is the `knowledge_seed` list in `tenants/bun2too.yaml`. A question with no matching seed escalates, which is correct behaviour, not a failure of this journey: use the question above.
