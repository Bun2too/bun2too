# Daily agent delivery and quality report

**Status:** implementation proposal; requires owner review through the ABR before production use.

## Why this exists

The report measures whether changes produce a working, verified product. Pull request volume, lines changed, and agent turns are activity measures; none is a delivery outcome. The report keeps activity beside delivery so a high-volume day with no passing QA is visible, without turning the numbers into an agent leaderboard.

## Initial scope

The first version reads GitHub metadata for the Relay `deploy-support` workflow. It uses UTC days and shows a rolling 30-day history. Historical `dev` deploy jobs whose intake step explicitly says `offline` appear in a separate retired-dev series; they never count as current QA delivery or live AI behavior. A later, separately reviewed change can add crew-team and website mirrors after their release workflows expose comparable deployment records. Production releases stay separate because they require human environment approval.

The collector does not read workflow logs, artifacts, PR bodies, review text, prompts, customer inquiries, model responses, or secrets. It reads workflow/run/job/step conclusions, timestamps, commit SHAs, PR state and file paths, and formal review states only.

## Measures

| Measure | Definition | Interpretation |
| --- | --- | --- |
| QA gate passes | A `deploy-support` run where the `qa / deploy` job and its `Intake journey` step both conclude `success`. | Automation completed deployment, smoke check, and the intake script. The script currently treats `rejected` as a terminal success, so this is **not** proof of an accepted customer outcome. |
| Verified customer outcomes | Count only when a future workflow publishes a sanitized structured outcome (`resolved`, `escalated`, or `awaiting_customer`) to the job summary or an output. | Currently **not instrumented**. Report as `not measured`, never infer it from a green job or count it as zero. |
| QA attempt failures | QA deploy jobs that conclude failure, grouped by the first failed step name. | Separates verification, infrastructure, deployment, smoke, and intake failures without reading log content. Cancelled runs are shown separately and excluded from failure rate. |
| QA gate completion rate | QA gate passes / non-cancelled QA attempts. | A process measure, not a product quality score. Show numerator and denominator. |
| Retired-dev offline checks | Historical `dev / deploy` runs whose intake step is explicitly labeled offline; report job/step completion only. | Context only. These runs do not exercise a live model or customer outcome; dev is no longer a deploy target and they never count toward current QA delivery. |
| Merged PRs by area and author class | Merged PRs grouped by changed path prefix and GitHub's `Bot`/`User` author type. | Context for delivery; never a target or ranking. Root-only PRs are their own group. No individual agent ranking. |
| PRs with requested changes | Merged PRs with at least one formal `CHANGES_REQUESTED` review before merge. | Rework context. It does not classify review as waste or infer coding effort. |
| Open-to-QA time | Median time from merged PR creation to its first matching successful QA gate run, when the deployed SHA exactly matches its merge SHA. | Label this **PR-to-QA time**, not coding time. Missing SHA matches remain unlinked rather than guessed. |
| Automated factory spend | Optional total only for paid factory runs whose workflow records a cost annotation. | Incomplete by design: interactive Claude, Codex, and Antigravity usage is not consistently instrumented. Never present this as total agent spend. |

Use the gate-pass count and failure stages as the primary view. Show merged PRs and rework as context. No per-agent score, rank, target quota, or color-coded individual performance. No composite productivity score.

## Historical view

Each daily page contains yesterday's UTC summary and a 30-day table with QA gate passes, non-cancelled QA attempts, failures, retired-dev offline checks, merged PRs, bot-authored PRs, requested-change PRs, and PR-to-QA time. Small Unicode bars beside gate-pass and failure counts make direction visible in Confluence without client-side macros. The daily report is recomputed from GitHub's retained metadata; it does not write a data branch or add `contents: write` to a workflow. The workflow also uploads a JSON/CSV artifact for 90 days. GitHub's API cannot distinguish a day with no runs from run metadata manually deleted before its normal retention period, so the report treats these as zero and states that limitation.

### Example page layout

```text
DAILY DELIVERY — 2026-11-23 UTC

QA release gate   0 passed / 1 attempt     no verified customer outcome signal
Failure stages    1 intake journey        cancelled: 0
PR context        3 merged                 1 had requested changes
PR-to-QA          not available             no successful matching SHA

30-day trend      gate passes  ▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏
                  QA failures  ▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏
```

The example values are illustrative, not historical data.

## Workflow and access

`.github/workflows/daily-agent-productivity.yml` runs at 10:17 UTC and on manual dispatch. It uses a read-only GitHub token (`contents: read`, `pull-requests: read`, `actions: read`) plus the explicit Confluence credentials `ATLASSIAN_EMAIL` and `ATLASSIAN_API_TOKEN`. It creates or updates a dated page under the configured Confluence folder. A failed API call fails the run; the workflow must never silently publish to another location. No new GitHub write permission or paid model call is needed.

The page publisher is idempotent by date and title. A retry updates that date's page instead of creating a duplicate. The API response body is not logged, and errors expose only the HTTP status and operation.

## Adoption of the added agent-engineering material

The 27 skills, command/persona files, references, hooks, and evaluation fixtures are a useful workflow library; they are not currently a coherent set of CI gates. Adopt a small, task-selected lifecycle:

1. **Define:** use `/spec` for multi-file or externally visible behavior; one-line fixes remain direct. Attach implementation to an owner-approved issue/spec, not an agent-invented scope.
2. **Plan:** use `/plan` only when the change has multiple independently verifiable slices. Avoid generating tickets and subagent bundles for a one-file fix.
3. **Build:** use `/build` test-first for behavior changes and one reviewable slice at a time.
4. **Verify:** run the touched product's existing CI/verify command and report live evidence separately from unit tests. Do not claim a deployment from a merge alone.
5. **Review:** keep Antigravity quality pass and the exact-head cross-review already required by root `AGENTS.md`. `/ship` must not launch additional three-persona review loops on every PR.
6. **De-slop:** use the writing-focused `de-slop` skill for externally published prose. It is not a code-quality gate and should not run on every response or source diff.

Do not merge every generic skill's default thresholds or tool examples into policy. Preserve the existing 65% coverage requirement. Keep product-specific skills beside their product for subtree portability; share a skill only after a second product needs the same instructions. Wire deterministic validators into CI only after their files are committed and their network, permissions, and dependencies are reviewed.

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

1. Owner/ABR accepts the metric definitions and the explicit `not measured` status for customer outcomes.
2. Add the two Confluence credentials as GitHub repository secrets; never put them in an `.env` committed to git or in this document.
3. Run `workflow_dispatch` once and verify the page is in folder `250970113`, the date is UTC, retry updates the same page, and no customer data or logs are present. If Confluence rejects a folder as the v2 page parent, stop and resolve the folder-parent API behavior rather than publishing to a different parent.
4. Keep the scheduled report for 30 days, compare its pass/failure trend to the raw GitHub run metadata, then decide whether crew-team and website should be added.
5. Add a sanitized Relay intake outcome to the job summary in a separate Relay-owned change before claiming customer outcomes. Until then, do not equate a successful script exit with an accepted resolution.
