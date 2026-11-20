# 0005. The factory's review loop fixes PRs in place and merges product PRs

- Status: accepted (decided by the repository owner, 2026-11-19)
- Date: 2026-11-19

## Context

The factory reviewed PRs but never closed the loop. Failed reviews were silent, and findings led to new PRs instead of fixes. Each round needed a person to relay, re-run or merge. That burned API credit without improving the code. The owner asked for one cycle per PR, with a person stepping in only when the loop cannot decide: change, commit, validate (CI), review, fix the PR in place on failure, repeat, and merge when everything passes.

## Decision

- **One loop per PR**, in `agent-review.yml` with `agent-rework.yml`. CI, then review, then on FAIL a rework round that pushes to the same PR, then a new review. Merge on PASS. No new PRs.
- **The loop merges product PRs.** It needs `VERDICT: PASS` and green `ci` on the exact head commit (`--match-head-commit`), and a same-repository branch. People still merge factory PRs (`.claude/`, `.cursor/`, `.github/`, `AGENTS.md`, `CLAUDE.md`, `docs/factory.md`, `docs/sdlc.md`) and approve prod deploys. AGENTS.md rule 9 says so. The owner removed the one-approval rule from the `main` ruleset for this.
- **A person is needed only when the loop stops:**
  - after `FACTORY_MAX_ROUNDS` rework rounds
  - after a round that fixed nothing, for example because the findings are in factory files
  - after a guard rejection

  A person's push restarts the loop.
- **The factory acts as the `bun2too-software-factory` GitHub App**, with a token minted per run.
- **Loop agents never hold that token.** Review, Rework and the formatting autofix run the PR's code or a model in jobs of their own with a read-only workflow token and only the model provider's key. Their output (a review file, or commits as patches) goes to a separate job on a fresh runner. That job posts the review, or applies the patches to a clean clone. It checks them with `rework-guard.sh` from the branch's own history, then pushes.
- **Provider, model and spend are settings:**
  - `FACTORY_PROVIDER`: anthropic, openai or gemini
  - `FACTORY_MODEL`
  - `FACTORY_MAX_BUDGET_USD`, a per-run cap
  - `FACTORY_ENABLED`, the off switch

  A red CI and a second trigger on an already-reviewed commit cost nothing.

## Consequences

- **A product PR can merge on a model's judgement alone.** Injected text in a diff could talk the reviewer into PASS. CI, the guard, same-repository branches and people merging factory PRs bound this. The audit trail is the review comment on each merged PR.
- **The rework agent runs repository code** (tests, the product's check command) with the model key loaded in its job. That alone would let a prompt-injected agent or a compromised dependency leak the key. The owner chose to close this rather than accept it, so AGENTS.md rule 11 requires five layers for any agent that runs code. They are listed in docs/factory.md under "Spend and safety":
  1. Dependencies install before the agent starts, after the lockdown and each in its own PID namespace, so no install script can leave a process behind. Every command the agent runs goes through a sandbox with no network.
  2. The model key is stripped from those commands' environment.
  3. The job's outbound traffic is limited to an allowlist, and the runner account loses `sudo` and Docker before the agent starts, so it cannot lift the block.
  4. The push job secret-scans the agent's patches and pushes nothing if a secret appears.
  5. The factory's key comes from its own provider workspace with a monthly spend limit, and holds nothing else.

  A provider that cannot sandbox commands (Gemini CLI today) gets no shell: it reviews from a diff file the workflow writes and does not run Rework. The review agent has no file-writing tools: its final message is the review. `--output` and `--ext-diff` are denied on `git diff/log/show` in any position, and the sandbox keeps `.git/config` and hooks read-only. The rework's patches are exported from a copy of `.git` with its config, hooks and attributes removed, so git never reads a file the agent could have edited.
- **Factory changes cannot be proven by the factory before merge.** Workflows run from the PR, but a person still merges them, and the first real run of a change is on the PR that carries it.
- **Implement, Ratchet and Retro still hold the app token while their agent runs**, so they are off unless `FACTORY_LEGACY_AGENTS=true`, until they move to the same split-job pattern. Explore (triage) only comments and labels issues.
- **Codex and Gemini review in one pass**, where Claude Code can run three reviewers in parallel. Their budget caps live in the provider's console, not in the workflow.
