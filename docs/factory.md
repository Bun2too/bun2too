# The factory: shared role spec

Automated runs in `.github/workflows/agent-*.yml` play the roles below. All roles live in this one file, with no separate agent file per role, so every product gets the same behaviour and a rule changes in one place. Each workflow prompt says "act as the <Role> role in docs/factory.md". The role then reads the `AGENTS.md` of the product it touches.

Vocabulary: a **task** is a kind of work, a **trigger** starts a **run**, and a **brake** stops bad output from moving on.

## Roles

| Role          | Trigger                                                  | Next             | Person re-enters                           | Dedupe                                        |
| ------------- | -------------------------------------------------------- | ---------------- | ------------------------------------------ | --------------------------------------------- |
| **Explore**   | issue opened, or labelled `needs-triage`                 | Implement        | `ready-for-human`                          | concurrency group per issue                   |
| **Implement** | issue labelled `ready-for-agent`                         | Review           | none until review passes                   | branch `agent/issue-<n>`                      |
| **Review**    | PR opened, synchronised, ready, or labelled `agent-review` | Rework on FAIL   | merges on PASS                             | concurrency group per PR, cancel in progress  |
| **Rework**    | review comment containing `VERDICT: FAIL`                | Review           | after 3 rounds: `ready-for-human`          | labels `rework-1..3`                          |
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

Follow [factory-review](../.claude/skills/factory-review/SKILL.md). Three reviewers run in parallel, each in a fresh context, and post one comment ending in a verdict line.

### Rework

Fix only the findings the latest review named.

1. List each finding as a checkbox. Fix those and nothing else.
2. If a finding is wrong, do not fix it. Reply with evidence (`file:line`, test output).
3. Run the product's check command; it must pass. Commit with `fix(review): ...` and push to the PR branch.
4. Comment the checklist with each item marked fixed or disputed.

The workflow enforces the cap: after `rework-3`, it labels the PR `ready-for-human` and stops.

### Hygiene

Run the product's autofix (`pnpm fix` for the support agent) and commit formatting-only changes as `bun2too-factory[bot]`.

### Ratchet

Remove the first entry from the product's `docs/factory/ratchet.txt` and make that path pass the stricter rule named there. Run the check command and open a PR labelled `ratchet`. Change nothing else.

### Retro

Read the merged PR, its issue, its reviews and its rework commits. For each mistake that recurred or that a person caught, add the strongest enforcer you can to the product's `docs/factory/enforcement.md` ladder: architecture > types > lint/CI > tests > review > docs. Open one PR labelled `retro`. If nothing recurred, do nothing.

## Brakes

1. **Automated checks:** each product's check command in `ci.yml`, plus `gitleaks`.
2. **Automated review:** a separate run with no memory of the implementation.
3. **Human review:** a person merges every PR and approves every prod deploy.

Start slow: a person applies `ready-for-agent` until ten agent PRs in a row merge without human rework. After that, Explore may apply it.

## Spend and safety

- Every agent workflow sets `timeout-minutes` and `--max-turns`.
- Agent runs use `FACTORY_TOKEN`, which grants contents, pull-requests and issues write. It cannot change workflows, and branch rules protect `main` and `.github/`.
- Runs that touch the factory (`.claude/`, `.cursor/`, `.github/`, `AGENTS.md`, `CLAUDE.md`, `docs/factory.md`, `docs/sdlc.md`) are never auto-merged and never chained.
- Deploy secrets live only in GitHub environments, which agent workflows never reference.
