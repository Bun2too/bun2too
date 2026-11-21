# The factory: shared role spec

Automated runs in `.github/workflows/agent-*.yml` play the roles below. All roles live in this one file, with no separate agent file per role, so every product gets the same behaviour and a rule changes in one place. Each workflow prompt says "act as the <Role> role in docs/factory.md". The role then reads the `AGENTS.md` of the product it touches.

Vocabulary: a **task** is a kind of work, a **trigger** starts a **run**, and a **brake** stops bad output from moving on.

## Roles

| Role          | Trigger                                                  | Next             | Person re-enters                           | Dedupe                                        |
| ------------- | -------------------------------------------------------- | ---------------- | ------------------------------------------ | --------------------------------------------- |
| **Explore**   | issue opened, or labelled `needs-triage`                 | Implement        | `ready-for-human`                          | concurrency group per issue                   |
| **Implement** | issue labelled `ready-for-agent`                         | Review           | none until review passes                   | branch `agent/issue-<n>`                      |
| **Review**    | a person labels the PR `agent-review` (rule 12), or the loop's own rework push; waits for CI | Merge on PASS, Rework on FAIL | a person merges factory PRs; the loop merges product PRs | concurrency group per PR, cancel in progress  |
| **Rework**    | the same review run, when its verdict is `FAIL`          | Review           | `ready-for-human` after `FACTORY_MAX_ROUNDS` rounds, a guard failure, or a round with no fix | labels `rework-<n>` |
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

The loop lives in one workflow, `agent-review.yml` (decision: [ADR 0005](adr/0005-factory-review-loop-merges-product-prs.md)), so a PR is changed, checked, reviewed and fixed in place, never by opening another PR:

1. A person adding the `agent-review` label starts the run, which takes the label off again (AGENTS.md rule 12). A plain push, a new PR or a PR marked ready starts nothing paid, so push as often as you like and ask for a review when the PR is ready. If this commit already has a review, the run reuses its verdict and calls no model. Otherwise it waits for `ci` on that commit.
2. If CI failed, its failing log becomes the review with `VERDICT: FAIL`, and no model runs. If CI passed, the agent reviews without write access; its final message is the review, which the workflow posts. The check passes only on `PASS`.
3. On `FAIL`, the run calls `agent-rework.yml`. If the PR changes the factory, rework hands it straight to a person, since the agent may not edit factory files and a person merges them anyway. Otherwise it puts the `agent-review` label back, commits fixes and pushes them to the PR. That push, made by the factory app with the label on, starts step 1 again. Nothing else continues the loop.
4. On `PASS` with CI green, the run rebase-merges the exact commit it reviewed. A PR that changes the factory is left for a person to merge. Factory paths are listed once, in `.github/scripts/factory-paths.regex`, which the merge gate reads from the base branch and the rework guard reads from the PR's history.
5. Otherwise the loop stops with `ready-for-human` when `FACTORY_MAX_ROUNDS` rounds did not pass, a round fixed nothing, or the guard rejected the fixes.

If the run ends without a review (an API error, a spent budget, a crash), the workflow posts "Factory review did not complete" with the cause and the run link, and fails the check, so a missing review is never silent. Agent output is shown in full in the run log.

In the review and rework runs the agent only reads and writes files in the workspace. It has no stored git credentials and never holds the app token: Claude Code gets the workflow token, which cannot push, and the other providers get none. The workflow posts every comment and does every push, which is what lets any provider run the agent. An agent can write anywhere on its runner, so it runs in a job of its own with a read-only token, and the app token and its private key never reach that runner. The review leaves as a file and the rework as patches. A separate job on a fresh runner posts the review, or applies the patches to a clean clone. It checks them there with the guard as committed before the round, and only then pushes.

The agents run as the `bun2too-software-factory` GitHub App, not the Claude GitHub app. The Claude app refuses to run on a PR that edits its own workflow, and pushes made with the default workflow token do not start new runs, so neither would close the loop.

### Rework

Answer the latest review: fix what it found at the cause, and nothing else.

1. Read the review in `.factory/review.md`, the PR diff and the `AGENTS.md` of each product the PR touches. List every Critical and Important finding as a checkbox. Suggestions are optional: take one only when it is in code you are already changing, and say so.
2. For each finding, confirm it first (reproduce it, or read the code at the `file:line` given). If it is wrong, do not change code: mark it **disputed** with evidence (`file:line`, command output).
3. Fix the cause, not the symptom:
   - When behaviour changes, add or change a test that fails before the fix and passes after it.
   - Never silence a finding. Adding a suppression (`noqa`, `type: ignore`, `eslint-disable`, `@ts-ignore`), skipping or focusing a test, deleting an assertion or loosening a threshold is not a fix. The workflow rejects the first three outright.
   - If a doc, ADR or comment describes the behaviour you changed, update it in the same commit.
4. Run the product's check command until it passes: `pnpm check` (support agent), `python3 scripts/verify_marketing.py` and `node --test evals/*.test.mjs` (crew team), `npm run docs:check && npm run typecheck && npm test` (website).
5. Commit one product per commit as `fix(<product>): <what>`, with the review link in the body. Commit only; do not push.
6. Write the checklist to `.factory/rework-report.md` and do not commit anything under `.factory/`. Mark each item **fixed** (with the commit and the test that proves it) or **disputed** (with evidence). List anything you could not run as **inconclusive**.

The workflow, not the agent, enforces the rest:
- Only the review run's own `FAIL` verdict starts a run; a comment typed by a person does not.
- Findings in factory files are listed as **needs a person**; the agent never edits them.
- A round with no commits labels the PR `ready-for-human`, since the review would fail again.
- Before pushing, it runs `.github/scripts/rework-guard.sh` over the new commits. It discards them and labels the PR `ready-for-human` if a commit touches more than one product, leaves the PR's products, edits factory files (including a `.claude/`, `.cursor/` or `.mcp.json` inside a product), or adds a suppression, skipped test or focused test.
- After `FACTORY_MAX_ROUNDS` rounds (default 3), it labels the PR `ready-for-human` and stops.
- When a person pushes to a PR handed to them, the review run removes `ready-for-human` and the `rework-*` labels, so the loop starts again with fresh rounds. Nobody has to clear labels by hand.

Its push starts a fresh review, so every round is reviewed again.

### Hygiene

Run the product's autofix (`pnpm fix` for the support agent) and commit formatting-only changes as `bun2too-software-factory[bot]`.

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

The factory is set with repository variables (Settings → Secrets and variables → Actions → Variables):

| Variable                 | Default             | Effect                                                                                              |
| ------------------------ | ------------------- | --------------------------------------------------------------------------------------------------- |
| `FACTORY_ENABLED`        | on                  | `false` stops every agent run; the workflows still run CI and the free checks                      |
| `FACTORY_PROVIDER`       | `anthropic`         | `anthropic`, `openai` (Codex) or `gemini` (Gemini CLI) for Review and Rework                        |
| `FACTORY_MODEL`          | `claude-sonnet-5-5` | The model for that provider. Required for `openai` and `gemini`                                     |
| `FACTORY_MAX_BUDGET_USD` | `0.50` | Hard spend cap per run. Enforced by Claude Code only; for the others, set a limit in the provider's console |
| `FACTORY_MAX_ROUNDS`     | `3`                 | Rework rounds before a person takes over (1–99; anything else means 3)                              |
| `FACTORY_MAX_RUNS_PER_DAY` | `4`               | Loop runs a day (UTC) across the repository, each at most one review and one rework round. Past it, a request gets a comment and no review |
| `FACTORY_MAX_USD_PER_DAY` | `0.40`            | No new loop run once the factory's agents have spent this much today (UTC). Each agent job leaves a `factory-cost` notice; the limit sums them. Claude Code only |
| `FACTORY_LEGACY_AGENTS`  | off                 | `true` turns on Explore, Implement, Ratchet and Retro, which do not meet rule 11 yet (ADR 0005)     |

The provider's key lives in the `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GEMINI_API_KEY` secret. Give the factory its own key, from a workspace or project with a monthly spend limit, so its usage shows up separately in the provider's console.

Explore, Implement, Ratchet and Retro still post to GitHub from inside an unsandboxed agent, so they do not meet rule 11. They are off unless `FACTORY_LEGACY_AGENTS=true`, run only when the provider is `anthropic`, and honour `FACTORY_ENABLED`, `FACTORY_MODEL` and `FACTORY_MAX_BUDGET_USD`. Until they move to the split-job pattern, a person triages issues.

Agents spend only when a person asks (AGENTS.md rule 12). One `agent-review` label is one request: a review, and on FAIL up to `FACTORY_MAX_ROUNDS` rework rounds, each followed by a review. A factory PR gets reviews only: rework never runs on one. Each loop run (a review, plus a rework round on a product PR) is capped at $0.50 per agent, and no run starts once the day's spend reaches `FACTORY_MAX_USD_PER_DAY`, so a day costs at most $0.40 plus the run in flight (at most $1.00) and four runs. Measured before these limits, on 2026-11-19 and 20: $4.35 in two days across 85 paid jobs, mostly reviews of one factory PR on every push and 22 rework rounds that could not change it. A red CI and a review of an already-reviewed commit cost nothing. `factory-sandbox-check` (under $0.01 on Haiku) also runs only on the label or from the Actions tab. No paid workflow runs on a schedule; the legacy roles are off (`FACTORY_LEGACY_AGENTS`).

- Every agent workflow sets `timeout-minutes` and a turn cap.
- Third-party actions that receive a provider key or the app token are pinned to a commit SHA. Gemini CLI, which runs without confirmations, gets only the tools in the run's allowlist.
- Agent runs use a token minted per run for the `bun2too-software-factory` GitHub App (`actions/create-github-app-token`, from the `FACTORY_APP_ID` variable and the `FACTORY_APP_PRIVATE_KEY` secret). It expires within an hour. Only a person edits `.github/` or `.claude/`: the rework guard rejects agent commits there and the merge job never merges a factory PR.
- PRs that touch the factory (the paths in `.github/scripts/factory-paths.regex`) are never auto-merged. The loop still reviews them and runs Rework on their product files. Rework never edits a factory file: findings there are listed as **needs a person**, and a round with nothing else to fix hands the PR over.
- Deploy secrets live only in GitHub environments, which agent workflows never reference.

### Agents that run code (AGENTS.md rule 11)

Rework runs the PR's code, its tests and its dependencies while the model key is loaded. Five layers keep that key from leaving the job:

1. **Sandboxed commands.** The lockdown (layer 3) comes first. Dependencies then install through `.github/scripts/contained.sh`. An install sees the filesystem read-only apart from its product folder and the package caches, with a private `/tmp` and its own PID namespace. So an install script cannot change what later steps run (the factory's actions, downloaded actions, `GITHUB_ENV`), and nothing it starts outlives it to read the agent's environment. Every command the agent runs then goes through an OS sandbox with no network, and there is no unsandboxed fallback. The agent program itself still reaches the model provider's API.
2. **No key in commands.** The model key is stripped from the environment of every command the agent runs. Codex keeps it in a separate proxy process.
3. **Outbound allowlist, no `sudo`.** `step-security/harden-runner` blocks every host the job does not need. It still allows the model APIs, GitHub and the package registries the install step uses, so it narrows a leak rather than stopping it; layer 1 is the boundary. Before the agent starts, the `factory-lockdown` action takes `sudo` and Docker away from the runner account, so nothing the agent runs can lift either block.
4. **Secret scan before anything leaves.** The jobs that post or push (`verdict` and the rework `push`) run the `secret-scan` action over everything the agent wrote: the review, the patches and the report. It runs gitleaks for known key formats and also matches the factory's own keys, as written and base64-encoded. If anything matches, or the scan cannot run, nothing is posted or pushed and the PR comment says why.
5. **A key worth little.** `ANTHROPIC_API_KEY` (or the OpenAI or Gemini secret) is the factory's own key, from a provider workspace with a monthly spend limit, used for nothing else.

Factory runs take no settings, hooks or MCP servers from the checkout (`--setting-sources user`, `--strict-mcp-config`): project settings outrank the factory's, so a PR could otherwise switch the sandbox off, and hooks and MCP servers would run outside it. The probe plants such settings and checks that nothing opens. Claude Code's file tools are also limited to the workspace and the toolchain caches, so they cannot read the key from `/proc` or the runner's temp files, and the agent cannot fetch web pages. Gemini CLI's file tools stay inside the workspace too, and layer 4 backs that up. The hygiene autofix also runs PR code, but no agent and no secret: it holds neither the model key nor the app token.

Accepted residual: the lockdown lets `/usr/bin/bwrap` create user namespaces through an AppArmor profile, since Claude Code's sandbox needs them. Ubuntu's restriction stays on for every other program, but the agent's sandboxed commands can create namespaces, which widens the kernel attack surface on a runner that holds the key. Kernel escapes are outside what this design defends against; a fresh VM per job bounds the damage.

Gemini CLI has no command sandbox in this setup, so it never gets a shell. Rework refuses `FACTORY_PROVIDER=gemini` and hands the PR to a person. Review still works with Gemini: the workflow writes the diff to `.factory/diff.patch` before any agent runs, and Gemini reads it with file tools only. A new role that gives an agent a shell must meet the same five layers before it is turned on.

`factory-sandbox-check.yml` proves the layers whenever their files change. An agent set up exactly like Rework runs `.github/scripts/sandbox-probe.sh`. The install step tries to write `GITHUB_ENV`, the factory's own action and the downloaded actions, and plants a process that tries to outlive it. The probe tries to read the key from its environment and from `/proc`, reach three hosts, use `sudo` and Docker, and run the toolchains and `git commit`. The workflow, not the agent, judges the results, and it also checks that the key appears nowhere in the agent's output.

## Tracing

Each `agent-review` run, its rework included, becomes one OpenTelemetry trace you can click through as a waterfall:

```text
agent-review PR #N                     the run
├── job prepare / review / verdict / rework / push / merge
│   └── step Run ./.github/actions/factory-agent
│       └── invoke_agent review        prompt, settings, allowlist, cost, refused tool calls
│           ├── chat <model>           one per model turn: input, reply, tokens, stop reason
│           ├── execute_tool Read      arguments, result, error
│           └── execute_tool Agent
│               └── invoke_agent <subagent>   its own turns and tool calls
```

Where to look:

- **The run's summary page** (Actions → the run, or the `run summary` link under each review comment). The `trace` job writes a job summary with a waterfall of the jobs and one per agent, then each turn's reply and tool calls, folded.
- **A trace backend**, for search, filters and side-by-side runs. Set the `FACTORY_OTLP_ENDPOINT` variable to any OTLP/HTTP endpoint and put its auth headers in the `FACTORY_OTLP_HEADERS` secret, as `key=value,key=value`. Set `FACTORY_TRACE_URL` to the backend's trace page with `{trace_id}` in it, and each review comment links straight to its trace. All GenAI spans follow the OpenTelemetry GenAI conventions, as Relay's do (bun2too-support-agent ADR 0004), so LLM-aware backends (Langfuse, LangSmith, Arize Phoenix) show turns as model calls with their input and output. Any OTLP backend (Grafana Tempo, Honeycomb, Jaeger) shows the waterfall.
- **The `trace` artifact** of every run (kept 30 days) holds the same trace as OTLP JSON. To view it with no account: `docker run -p 16686:16686 -p 4318:4318 jaegertracing/jaeger`, then `curl -H 'Content-Type: application/json' --data @trace.otlp.json localhost:4318/v1/traces`, and open `localhost:16686`.

The trace ID is the first 32 hex characters of the SHA-256 of `owner/repo/run_id/run_attempt`. Every round of a PR shares `session.id` = `owner/repo#N`, so a backend can group a PR's rounds.

To change what you see in a trace, edit the role's prompt and settings where the `factory.prompt.source` attribute points: `agent-review.yml` and the `factory-review` skill for Review, `agent-rework.yml` for Rework, and `.github/actions/factory-agent` for the settings every agent shares.

How it stays inside rule 11: the agent jobs only save Claude Code's session transcripts, settings and run record (`trace-dir` on the `factory-agent` action) and upload them for one day. The `trace` job, on a runner no agent touched, secret-scans them, builds the trace with `.github/scripts/factory-trace.py`, sends it, and deletes the raw uploads. If the scan finds anything, prompts, replies and tool input and output are left out; timings, token counts and tool names still go out. The agent jobs hold no backend credentials, and the backend is not on their allowlist.

Limits: Claude Code's transcripts usually keep only a marker for thinking, not its text, so each turn shows whether the model thought, and the text only when it was recorded. Codex and Gemini leave no transcript, so their agent is a single span. A run cancelled by a newer push leaves no trace.
