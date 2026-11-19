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
- **Agents never hold that token.** They run in jobs of their own with a read-only workflow token and only the model provider's key. Their output (a review file, or commits as patches) goes to a separate job on a fresh runner. That job posts the review, or applies the patches to a clean clone. It checks them with `rework-guard.sh` from the branch's own history, then pushes.
- **Provider, model and spend are settings:**
  - `FACTORY_PROVIDER`: anthropic, openai or gemini
  - `FACTORY_MODEL`
  - `FACTORY_MAX_BUDGET_USD`, a per-run cap
  - `FACTORY_ENABLED`, the off switch

  A red CI and a second trigger on an already-reviewed commit cost nothing.

## Consequences

- **A product PR can merge on a model's judgement alone.** Injected text in a diff could talk the reviewer into PASS. CI, the guard, same-repository branches and people merging factory PRs bound this. The audit trail is the review comment on each merged PR.
- **The rework agent runs repository code** (tests, the product's check command), so it can reach the network while the model key is in its environment. A prompt-injected agent could leak that key. Accepted for now and bounded: the factory's key comes from its own provider workspace with a monthly spend limit, and holds nothing else. Restricting the agent job's network egress is the follow-up that closes this.
- **Factory changes cannot be proven by the factory before merge.** Workflows run from the PR, but a person still merges them, and the first real run of a change is on the PR that carries it.
- **Codex and Gemini review in one pass**, where Claude Code can run three reviewers in parallel. Their budget caps live in the provider's console, not in the workflow.
