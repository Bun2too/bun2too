---

name: verify-relay
description: Launch the Relay stack locally (gateway + agents, offline fakes by default), drive it through its real HTTP and A2A surfaces like a channel or partner agent would, and capture evidence. Use before declaring any customer-, operator- or partner-visible change done, or to reproduce a bug.
---

# Verify Relay

Drives the real processes over HTTP. Offline mode swaps only the external systems for deterministic stand-ins: the keyword classifier and `KnowledgeLookupSpecialist` replace model calls, and `relay_agents.connectors.fakes` replaces Jira and ServiceNow. The gateway, graph, state machine, policy and store run for real.

## Launch

```sh
pnpm install && uv sync --directory services/agents
RELAY_OFFLINE=1 pnpm dev
```

Ready when both lines appear: `relay-agents listening on :8000` and `relay-gateway listening on :8787`. For traces, start the collector and Jaeger first with `pnpm stack:up` (UI at http://localhost:16686). Teardown is the Cleanup section.

## Doctor

```sh
curl -fsS localhost:8787/healthz && curl -fsS localhost:8000/healthz
```

Both must return `{"ok":true,...}` with `"offline":true` when you launched offline. If a port answers but Doctor fails, another process owns it: do not drive it.

## Drive

Use the helper, which posts an intake, polls until the case leaves `received`/`triaged`/`ticketed`/`in_progress`, and saves every response:

```sh
scripts/verify/intake.sh "I can't log in, the reset email never arrives" web_widget
```

Arguments: message text, channel. Environment: `RELAY_GATEWAY` (default `http://localhost:8787`), `RELAY_TENANT_KEY` (default `dev-bun2too-key`). Feature-specific journeys are in `features/`.

## Evidence

The helper writes `.verify/<UTC timestamp>/`: `intake.json` (202 response), `case.json` (final case), `events.json` (case event log), `trace_id.txt`. A proof shows the intake, the resulting state, and the side effects: the case's `tickets` must include one `jira` and one `servicenow` reference. Put the folder path and the trimmed `events.json` in the PR body.

## Cleanup

Stop the `pnpm dev` process you started (Ctrl-C in its terminal, or `kill <pid>` of the PID you launched). `pnpm stack:down` stops the containers. Never kill by process name. Evidence in `.verify/` stays.

## Helpers

- `scripts/verify/intake.sh <message> [channel]`: described above; exits non-zero if the case never settles within 30 seconds.
- `scripts/verify/a2a.sh <message>`: same journey through `POST /a2a` (`message/send`, then `tasks/get`).
