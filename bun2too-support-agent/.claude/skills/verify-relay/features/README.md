# Relay feature map

| Feature                        | File                             | Proof of work                                                   |
| ------------------------------ | -------------------------------- | --------------------------------------------------------------- |
| REST intake to auto-resolution | [rest-intake.md](rest-intake.md) | case `resolved`, two tickets, events in order                   |
| Escalation                     | [escalation.md](escalation.md)   | case `escalated`, handoff note on both tickets                  |
| A2A intake                     | [a2a-intake.md](a2a-intake.md)   | A2A task reaches `completed` or `working` with the same case ID |
| Idempotent intake              | [idempotency.md](idempotency.md) | same `Idempotency-Key` returns the same case ID                 |
