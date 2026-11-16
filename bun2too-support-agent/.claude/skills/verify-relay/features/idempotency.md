# Idempotent intake

## Sub-features

Gateway requires `Idempotency-Key`; agents service returns the existing case for a repeated key.

## How to get to it (user POV)

A channel retries a POST after a timeout.

## Driving it with curl

Run `scripts/verify/intake.sh` twice with `RELAY_IDEMPOTENCY_KEY=fixed-1` set. Both `intake.json` files must show the same `caseId`, and the second `case.json` must still list exactly one ticket per system.

## Gotchas

Keys are scoped per tenant.
