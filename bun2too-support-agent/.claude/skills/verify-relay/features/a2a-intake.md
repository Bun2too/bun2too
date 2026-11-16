# A2A intake

## Sub-features

Agent card discovery, `message/send`, `tasks/get`, task-state mapping.

## How to get to it (user POV)

A partner's agent reads `/.well-known/agent-card.json` and sends a JSON-RPC `message/send` to `/a2a`.

## Driving it with curl

`curl -s localhost:8787/.well-known/agent-card.json` then `scripts/verify/a2a.sh "My API webhook returns 401"`.

Expected: `message/send` returns a `task` whose `id` equals a Relay case ID; `tasks/get` later returns `completed` (resolved) or `working` with metadata `relayStatus: escalated`.

## Gotchas

Streaming (`message/stream`) is not implemented yet; the agent card advertises `streaming: false`.
