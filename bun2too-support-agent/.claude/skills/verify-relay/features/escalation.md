# Escalation

## Sub-features

Privacy intents always escalate; low confidence escalates; the handoff summary is written to both tickets.

## How to get to it (user POV)

A customer asks to delete their data.

## Driving it with curl

`scripts/verify/intake.sh "Please delete all my personal data" web_widget`

Expected: `status` = `escalated`, `classification.intent` = `privacy`, last event `reason` names the policy rule.

## Gotchas

None known.
