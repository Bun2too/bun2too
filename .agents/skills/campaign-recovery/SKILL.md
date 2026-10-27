---
name: campaign-recovery
description: Diagnose and recover failed or approval-blocked daily marketing campaigns using persisted run evidence and bounded recovery paths.
---

Read `docs/operational-recovery.md` and the relevant dated incident report. Retrieve authenticated `/runs/{id}` and `/runs/{id}/work`; show only sanitized diagnostics. Match the reported run ID, attempt, publication window and actual deployment revision.

Distinguish provider exceptions from content rejection and unknown Facebook outcomes. For review blocks inspect current source snapshots, artifact citations, exact blocker strings, and both reviewers. Historical publications are exclusions, not a citation allowlist. An empty Delivery blocker list never overrides reviewer rejection.

Repair the cause before recovery. Provider billing/authentication failures require restored access and explicit resume. Content defects use `/runs/{id}/revise-content` only after the correction is deployed and while the original window is valid. The endpoint preserves rejected work and requires fresh reviews. Never reopen an expired slot or automatically replay an uncertain Facebook send.

Use `scripts/verify_marketing.py` for local regressions. Verify live deployment and subsequent run outcomes separately. Report queued/approved/published states precisely. Slack API acceptance is delivery evidence; retained blocked email records are not sent email. Keep credentials and raw private artifacts out of context files.
