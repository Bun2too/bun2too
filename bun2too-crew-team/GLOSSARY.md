# Marketing crew glossary

These terms describe implemented runtime behavior. See [persistent context](docs/agent-context.md), [editorial tracking](docs/editorial-and-agent-tracking.md), [recovery](docs/operational-recovery.md) and [evaluations](docs/agent-evaluations.md).

| Term | Meaning and boundary |
| --- | --- |
| Marketing crew | Self-hosted CrewAI roles inside one FastAPI service. They produce structured campaign deliverables, not independently deployed servers or factory coding agents. |
| Scheduled campaign | Durable daily article/Facebook workflow with a persisted slot, target/window, source snapshots and publication policy. |
| Manual campaign | Operator-requested draft/backlog workflow; has different role ordering and review behavior from scheduled generation. |
| Social-only flow | Researcher → Writer → Editor → Delivery; not the nine-role scheduled article path. |
| Run / attempt | Persisted execution and its generation attempt history. A retry retains the original window and audit evidence. |
| Source snapshot | Current retrieved evidence and exact citation allowlist. Publication-history URLs do not become current evidence. |
| Editorial exclusions | Recent published titles/source stories used to avoid repetition; not drafts to copy or proof of a new claim. |
| AgentDeliverable | Structured role output with decisions, evidence, risks and work. Execution completion is not a quality score. |
| MarketingArtifact | Delivery's validated final campaign package. Empty blockers cannot override Editor/Tester rejection. |
| Final-copy review | Scheduled Editor edits, then Tester independently checks that candidate; Delivery preserves it exactly. Manual ordering differs. |
| Approved-content hash | Application SHA-256 binding publication to approved copy; later edits require fresh review. |
| Publication claim | Durable claim committed before an external send. Unknown/sending outcomes require reconciliation, not blind replay. |
| Reconciliation | Verify/adopt an observed remote result after ambiguity without issuing another public send. |
| Content revision | Explicit bounded regeneration after a content defect; preserves rejected evidence and requires fresh reviews within the existing window. |
| Insights projection | Public view of approved runs marked published. Excludes drafts, prompts, reviewer records and private diagnostics. |
| Digest / Web Push | Separate opt-in delivery channels with durable claims. Auth0 verified newsletter/topic consent controls digests; browser permission controls push. |
| Runtime automatic approval | Configured content-policy decision for a campaign; does not approve a software production release. |
| Operational evaluation | Run evidence/quality measurements ingested or computed by the service; distinct from CI's independent model-judge gates. |
| Component / trajectory evaluation | Scores each observed LLM call / the visible complete tested workflow. Every relevant dimension must be at least 0.5. |
| Measured cost | Estimate from observed usage and a versioned rate card. Unknown usage is not zero; between-call budgets are not account hard limits. |

Keep **marketing run**, **factory run**, **website inquiry** and **Relay case** distinct. Model reasoning is not an observable deliverable; retain visible structured decisions and evidence instead.
