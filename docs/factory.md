# The factory: shared role spec

Automated runs in `.github/workflows/agent-*.yml` play the roles below. All roles live in this one file, with no separate agent file per role, so every product gets the same behaviour and a rule changes in one place. Each workflow prompt says "act as the <Role> role in docs/factory.md". The role then reads the `AGENTS.md` of the product it touches.

Vocabulary: a **task** is a kind of work, a **trigger** starts a **run**, and a **brake** stops bad output from moving on.

## Roles

| Role          | Trigger                                                  | Next             | Person re-enters                           | Dedupe                                        |
| ------------- | -------------------------------------------------------- | ---------------- | ------------------------------------------ | --------------------------------------------- |
| **Explore**   | issue opened, or labelled `needs-triage`                 | Implement        | `ready-for-human`                          | concurrency group per issue                   |
| **Implement** | issue labelled `ready-for-agent`                         | Review           | none until review passes                   | branch `agent/issue-<n>`                      |
| **Review**    | PR opened, synchronised, ready, or labelled `agent-review`; waits for CI | Merge on PASS, Rework on FAIL | merges factory PRs only          | concurrency group per PR, cancel in progress  |
| **Rework**    | the same review run, when its verdict is `FAIL`          | Review           | `ready-for-human` after 3 rounds, a guard failure, or a round with no fix | labels `rework-1..3` |
| **Hygiene**   | push to a PR branch                                      | CI               | never                                      | skips its own commits                         |
| **Ratchet**   | daily 06:00 UTC                                          | Review           | merges                                     | one open `ratchet` PR                         |
| **Retro**     | every 10th merged PR                                     | Review           | merges, always                             | one open `retro` PR                           |

### Explore

Triage exactly one issue. Never edit files or push.

1. Identify the product from the issue's `area:*` label or its content. Read that product's `AGENTS.md`, `GLOSSARY.md` if present, and the ADRs whose titles touch the area.
2. Restate the issue in the product's terms in two sentences.
3. Check every factual claim against the code, quoting `file:line`.
4. For a bug, reproduce it on the cheapest real path (a unit test or the product's verify skill). Record the command and its output.
5. Choose one label and post one comment covering your findings, the reproduction, the label and why it fits. For `ready-for-agent`, also name the test seams.
   - `ready-for-agent`: clear, fits one PR, needs no credentials or product judgment.
   - `needs-info`: a fact only the reporter has is missing. Ask for it once.
   - `ready-for-human`: needs judgment, credentials, production access, or touches the factory.
   - `wontfix`: out of scope.

While the Implement trigger is manual (see [Brakes](#brakes)), recommend `ready-for-agent` in your comment instead of applying it.

### Implement

Implement one ticket on branch `agent/issue-<n>` and open a draft PR.

1. Read the product's `AGENTS.md`, its coding standards, and the issue with comments (`gh issue view <n> --comments`). Install the product's dependencies as its `AGENTS.md` says.
2. Run `/build` on the ticket: test-first at the seams the Explore comment named, one slice per commit, Conventional Commits scoped to the product (`feat(support-agent): ...`).
3. Keep to the ticket. Touch only the product's subtree, plus root files when the ticket says so.
4. Run the product's check command until it passes. For prompt changes, include eval numbers from before and after.
5. Prove observable behaviour with the `verifier` agent and keep the evidence.
6. Open a draft PR with `gh pr create --draft`. Format the body with `/pr`: the smallest visual summary, evidence with exact commands, a merge-danger call, and `Closes #<n>`.

If you need product judgment or credentials, stop. Comment the exact question on the issue and label it `ready-for-human`. Do not wait.

### Review

Follow [factory-review](../.claude/skills/factory-review/SKILL.md). Three reviewers run in parallel, each in a fresh context, and post one comment. Its first line names the reviewed commit and its last line is the verdict: `PASS`, `FAIL` (starts Rework) or `INCONCLUSIVE` (a reviewer could not finish; a person decides).

The loop lives in one workflow, `agent-review.yml`, so a PR is changed, checked, reviewed and fixed in place, never by opening another PR:

1. A push to the PR starts the run. It waits for `ci` on that commit and hands any failing step to the reviewers as a Critical finding.
2. The review posts its comment. The check passes only on `PASS`.
3. On `FAIL`, the run calls `agent-rework.yml`, which commits fixes and pushes them to the PR. The push starts step 1 again.
4. On `PASS` with CI green, the run rebase-merges the exact commit it reviewed. A PR that changes the factory is left for a person to merge.
5. Otherwise the loop stops with `ready-for-human` when three rounds did not pass, a round fixed nothing, or the guard rejected the fixes.

If the run ends without that comment (an API error, a usage limit, a crash), the workflow posts "Factory review did not complete" with the run link and fails the check, so a missing review is never silent. Agent output is shown in full in the run log.

The agents run as the `bun2too-software-factory` GitHub App, not the Claude GitHub app. The Claude app refuses to run on a PR that edits its own workflow, and pushes made with the default workflow token do not start new runs, so neither would close the loop.

### Rework

Answer the latest review: fix what it found at the cause, and nothing else.

1. Read the review the workflow names, the PR diff and the `AGENTS.md` of each product the PR touches. List every Critical and Important finding as a checkbox. Suggestions are optional: take one only when it is in code you are already changing, and say so.
2. For each finding, confirm it first (reproduce it, or read the code at the `file:line` given). If it is wrong, do not change code: mark it **disputed** with evidence (`file:line`, command output).
3. Fix the cause, not the symptom:
   - When behaviour changes, add or change a test that fails before the fix and passes after it.
   - Never silence a finding. Adding a suppression (`noqa`, `type: ignore`, `eslint-disable`, `@ts-ignore`), skipping or focusing a test, deleting an assertion or loosening a threshold is not a fix. The workflow rejects the first three outright.
   - If a doc, ADR or comment describes the behaviour you changed, update it in the same commit.
4. Run the product's check command until it passes: `pnpm check` (support agent), `python3 scripts/verify_marketing.py` and `node --test evals/*.test.mjs` (crew team), `npm run docs:check && npm run typecheck && npm test` (website).
5. Commit one product per commit as `fix(<product>): <what>`, with the review link in the body. Commit only; do not push.
6. Write the checklist to `rework-report.md` at the repository root and do not commit it. Mark each item **fixed** (with the commit and the test that proves it) or **disputed** (with evidence). List anything you could not run as **inconclusive**.

The workflow, not the agent, enforces the rest:
- Only the review run's own `FAIL` verdict starts a run; a comment typed by a person does not.
- Findings in factory files are listed as **needs a person**; the agent never edits them.
- A round with no commits labels the PR `ready-for-human`, since the review would fail again.
- Before pushing, it runs `.github/scripts/rework-guard.sh` over the new commits. It discards them and labels the PR `ready-for-human` if a commit touches more than one product, leaves the PR's products, edits factory files, or adds a suppression, skipped test or focused test.
- After `rework-3`, it labels the PR `ready-for-human` and stops.

Its push starts a fresh review, so every round is reviewed again.

### Hygiene

Run the product's autofix (`pnpm fix` for the support agent) and commit formatting-only changes as `bun2too-factory[bot]`.

### Ratchet

Remove the first entry from the product's `docs/factory/ratchet.txt` and make that path pass the stricter rule named there. Run the check command and open a PR labelled `ratchet`. Change nothing else.

### Retro

Read the merged PR, its issue, its reviews and its rework commits. For each mistake that recurred or that a person caught, add the strongest enforcer you can to the product's `docs/factory/enforcement.md` ladder: architecture > types > lint/CI > tests > review > docs. Open one PR labelled `retro`. If nothing recurred, do nothing.

## Brakes

1. **Automated checks:** each product's check command in `ci.yml`, plus `gitleaks`.
2. **Automated review:** a separate run with no memory of the implementation.
3. **Human review:** a person merges every factory PR and approves every prod deploy. Product PRs merge when CI and the review pass.

Start slow: a person applies `ready-for-agent` until ten agent PRs in a row merge without human rework. After that, Explore may apply it.

## Spend and safety

- Every agent workflow sets `timeout-minutes` and `--max-turns`.
- Agent runs use a token minted per run for the `bun2too-software-factory` GitHub App (`actions/create-github-app-token`, from the `FACTORY_APP_ID` variable and the `FACTORY_APP_PRIVATE_KEY` secret). It expires within an hour. Only a person edits `.github/` or `.claude/`: the rework guard rejects agent commits there and the merge job never merges a factory PR.
- Runs that touch the factory (`.claude/`, `.cursor/`, `.github/`, `AGENTS.md`, `CLAUDE.md`, `docs/factory.md`, `docs/sdlc.md`) are never auto-merged and never chained.
- Deploy secrets live only in GitHub environments, which agent workflows never reference.
