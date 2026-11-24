# Daily agent delivery and quality report

**Status:** metric definitions accepted by the owner; implementation remains subject to exact-head review and configuration checks.

## Why this exists

The report measures whether changes produce a working, verified product. Pull request volume, lines changed, and agent turns are activity measures; none is a delivery outcome. The report keeps activity beside delivery so a high-volume day with no passing QA is visible, without turning the numbers into an agent leaderboard.

## Initial scope

The first version reads GitHub metadata for the Relay `deploy-support` workflow. It uses UTC days and shows a rolling 30-day history. Historical `dev` deploy jobs whose intake step explicitly says `offline` appear in a separate retired-dev series; they never count as current QA delivery or live AI behavior. A later, separately reviewed change can add crew-team and website mirrors after their release workflows expose comparable deployment records. Production releases stay separate because they require human environment approval.

The collector does not read workflow logs, artifacts, PR bodies, review text, prompts, customer inquiries, model responses, or secrets. It reads workflow/run/job/step conclusions, timestamps, commit SHAs, PR state and file paths, and formal review states only.

## Measures

| Measure | Definition | Interpretation |
| --- | --- | --- |
| Delivered (owner-defined) | A `deploy-support` run where the `qa / deploy` job and its `Intake journey` step both conclude `success`. | The owner defines delivery as QA green. This verifies the deployment, smoke check, and intake gate. Because the script treats `rejected` as terminal success, it does not prove an accepted resolution. |
| QA attempt failures | QA deploy jobs that conclude failure, grouped by the first failed step name. | Separates verification, infrastructure, deployment, smoke, and intake failures without reading log content. Cancelled runs are shown separately and excluded from failure rate. |
| QA gate completion rate | QA gate passes / non-cancelled QA attempts. | A process measure, not a product quality score. Show numerator and denominator. |
| Awaiting production approval | QA-green workflow runs in `waiting` state whose pending-deployments response names `support-prod`. | A separate snapshot of the human release gate. It is not counted as QA delivery. |
| Retired-dev offline checks | Historical `dev / deploy` runs whose intake step is explicitly labeled offline; report job/step completion only. | Context only. These runs do not exercise a live model or customer outcome; dev is no longer a deploy target and they never count toward current QA delivery. |
| Merged PRs by area and author class | Merged PRs grouped by changed path prefix and GitHub's `Bot`/`User` author type. | Context for delivery; never a target or ranking. Root-only PRs are their own group. No individual agent ranking. |
| PRs with requested changes | Merged PRs with at least one formal `CHANGES_REQUESTED` review before merge. | Rework context. It does not classify review as waste or infer coding effort. |
| Open-to-QA time | Median time from merged PR creation to its first matching successful QA gate run, when the deployed SHA exactly matches its merge SHA. | Label this **PR-to-QA time**, not coding time. Missing SHA matches remain unlinked rather than guessed. |
| Automated factory spend | Optional total only for paid factory runs whose workflow records a cost annotation. | Incomplete by design: interactive Claude, Codex, and Antigravity usage is not consistently instrumented. Never present this as total agent spend. |

Use the delivered count and failure stages as the primary view. Show merged PRs and rework as context. No per-agent score, rank, target quota, or color-coded individual performance. No composite productivity score.

## Historical view

Each daily page contains yesterday's UTC summary and a 30-day table with QA gate passes, non-cancelled QA attempts, failures, retired-dev offline checks, merged PRs, bot-authored PRs, requested-change PRs, and PR-to-QA time. It also shows a current snapshot of QA-green workflow runs in `waiting` state whose `pending_deployments` API response identifies `support-prod`. The workflow-jobs API does not expose an environment field, so the report uses GitHub's pending-deployments endpoint for this environment-specific snapshot. Small Unicode bars beside gate-pass and failure counts make direction visible in Confluence without client-side macros. The daily report is recomputed from GitHub's retained metadata; it does not write a data branch or add `contents: write` to a workflow. The workflow also uploads a JSON/CSV artifact for 90 days. GitHub's API cannot distinguish a day with no runs from run metadata manually deleted before its normal retention period, so the report treats these as zero and states that limitation.

### Example page layout

```text
DAILY DELIVERY — 2026-11-23 UTC

QA release gate   0 delivered / 1 attempt  production approval: separate
Failure stages    1 intake journey        cancelled: 0
PR context        3 merged                 1 had requested changes
PR-to-QA          not available             no successful matching SHA

30-day trend      delivered    ▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏
                  QA failures  ▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏
```

The example values are illustrative, not historical data.

## Workflow and access

`.github/workflows/daily-agent-productivity.yml` runs at 10:17 UTC and on manual dispatch from `main`. It uses a read-only GitHub token (`contents: read`, `pull-requests: read`, `actions: read`) and a `metrics` GitHub environment. That environment supplies `CONFLUENCE_BASE_URL` and `CONFLUENCE_CLOUD_ID` as variables and `CLAUDE_ATLASSIAN_CLIENT_ID` / `CLAUDE_ATLASSIAN_CLIENT_SECRET` as secrets. The cloud ID is available from `https://bun2too.atlassian.net/_edge/tenant_info`; it is a non-secret site identifier. The publisher exchanges the service-account OAuth 2LO credential for a short-lived token, then uses the Confluence REST v2 API via `api.atlassian.com`. Configure granular scopes `read:space:confluence`, `read:folder:confluence`, `read:page:confluence`, and `write:page:confluence`, and grant the service account access to the target space and folder. Restrict the environment to `main`; do not add a required reviewer, because the scheduled report must run unattended. A failed API call fails the run; the workflow must never silently publish to another location. No new GitHub write permission or paid model call is needed. See [Atlassian service-account OAuth documentation](https://support.atlassian.com/user-management/docs/create-oauth-2-0-credential-for-service-accounts/) and [Confluence OAuth scope documentation](https://developer.atlassian.com/cloud/confluence/scopes-for-oauth-2-3lo-and-forge-apps/).

The page publisher is idempotent by date and title. A retry updates that date's page instead of creating a duplicate. The API response body is not logged, and errors expose only the HTTP status and operation.

## Adoption of the added agent-engineering material

The 27 skills, command/persona files, references, hooks, and evaluation fixtures are a useful workflow library; they are not currently a coherent set of CI gates. Adopt a small, task-selected lifecycle:

1. **Define:** use `/spec` for multi-file or externally visible behavior; one-line fixes remain direct. Attach implementation to an owner-approved issue/spec, not an agent-invented scope.
2. **Plan:** use `/plan` only when the change has multiple independently verifiable slices. Avoid generating tickets and subagent bundles for a one-file fix.
3. **Build:** use `/build` test-first for behavior changes and one reviewable slice at a time.
4. **Verify:** run the touched product's existing CI/verify command and report live evidence separately from unit tests. For incident fixes, link sanitized failure evidence before coding. A failed QA gate pauses new scope in that product until its root cause and owner-approved correction are recorded; unrelated products may proceed. Do not claim a deployment from a merge alone.
5. **Review:** keep Antigravity quality pass and the exact-head cross-review already required by root `AGENTS.md`. `/ship` must not launch additional three-persona review loops on every PR.
6. **De-slop:** use the writing-focused `de-slop` skill for externally published prose. It is not a code-quality gate and should not run on every response or source diff.

Do not merge every generic skill's default thresholds or tool examples into policy. Preserve the existing 65% coverage requirement. Keep product-specific skills beside their product for subtree portability; share a skill only after a second product needs the same instructions. Wire deterministic validators into CI only after their files are committed and their network, permissions, and dependencies are reviewed. Keep at most one process or agent-workflow PR open at a time so process changes do not crowd out product delivery.

## Scan findings to resolve before enabling skill CI

- The new validation and eval scripts are not called by the current CI workflows, so they currently provide no merge gate.
- `docs/agents.md` contains relative links to `../agents/*.md`; the persona documents are actually under `docs/agents/`.
- Command copies under `commands/` and `.gemini/commands/` differ in several files and have no declared source of truth.
- The active WebFetch cache hook accepts a URL from hook input and performs a HEAD request without restricting schemes/hosts/private addresses. Its URL-only cache key can reuse content across prompts; debug mode can log prompt-shaped input; cache files are not ignored. Keep it disabled until those risks are fixed and reviewed.
- Tier 3 `scripts/run-evals.js` gives the local Claude process Bash, edit/write and network tools, inherits the caller environment, and uses `acceptEdits`. Do not run it with credentials or enable it in CI until OS-level network/credential isolation exists. The opt-in label alone is not a sandbox.
- The `de-slop` instructions target prose and include a nonexistent `Intelligence/de-slop-log.md` path. Fix its output contract before treating its log as evidence.
- Several personas are documentation only, not discoverable subagents for every harness. Commands must not claim that those tools ran unless they did.

These are review findings, not automatic delete instructions. The additions are untracked user work and must be preserved until their owner decides how to stage or revise them.

## Rollout

1. The owner accepted UTC reporting and defined delivery as QA green. Keep the rejection-state caveat and the separate `support-prod` approval count visible.
2. Add `CONFLUENCE_BASE_URL` and `CONFLUENCE_CLOUD_ID` as variables and `CLAUDE_ATLASSIAN_CLIENT_ID` / `CLAUDE_ATLASSIAN_CLIENT_SECRET` as secrets in the GitHub `metrics` environment; restrict that environment to `main`. Never put credential values in git or in this document.
3. Run `workflow_dispatch` once and verify the page is in folder `250970113`, the date is UTC, retry updates the same page, and no customer data or logs are present. The current read-only OAuth check returned `scope does not match` because the credential has classic scopes; update it to the granular scopes above first. If Confluence rejects a folder as the v2 page parent, stop and resolve the folder-parent API behavior rather than publishing to a different parent.
4. Keep the scheduled report for 30 days, compare its pass/failure trend to the raw GitHub run metadata, then decide whether crew-team and website should be added.
5. Add a sanitized Relay intake outcome to the job summary in a separate Relay-owned change before claiming customer outcomes. Until then, do not equate a successful script exit with an accepted resolution.
