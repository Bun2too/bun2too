# Lead agents: how Claude and Codex work together

Two lead agents build Bun2too with the owner: **Claude** (Claude Code) and **Codex**. They run side by side in a [herdr](https://herdr.dev) workspace. Each owns part of the monorepo, works only in its own checkout, and reviews the other's work before a person acts on it. Neither replaces the owner's judgement, CI or the factory's review. This page is the protocol; AGENTS.md rule 13 points here.

## Ownership

| Area                                                                                    | Owner  |
| --------------------------------------------------------------------------------------- | ------ |
| `bun2too-website/`, `bun2too-crew-team/`                                                | Codex  |
| `bun2too-support-agent/`                                                                | Claude |
| The factory: `.github/`, `.claude/`, `docs/factory.md`, `docs/sdlc.md`, `docs/adr/`     | Claude |
| Shared root files: `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/agents/`, `docs/sop/`, `docs/specs/` | Both   |

The owner of an area decides how it changes. Either agent may change a shared root file, but only in a PR the other has reviewed. An agent that needs a change in the other's area asks for it (an issue or a prompt) instead of making it. The exception is a one-line fix that blocks its own work, which then goes in a PR the area's owner reviews.

## One checkout each

- Each agent works in its own checkout or `git worktree`, on its own branches: `claude/*` and `codex/*`. Neither commits to, rebases or switches the other's branch, and neither touches the other's uncommitted files. AGENTS.md rule 6 applies between the agents as it does to people.
- Before editing, run `git status --short` and `git branch --show-current` in your own checkout.
- Base a branch on `origin/main`. If it has to build on an open PR, say so in its description and rebase it onto `main` once that PR merges, so it never carries the other PR's commits.
- Commit only paths you changed (`git add <paths>`, never `git add -A`).

## Cross-review

Every PR either agent opens is reviewed by the other before a person merges it, and before anyone asks the factory to review it (the `agent-review` label).

- The review is one PR comment. It starts with `Reviewed commit: <full SHA>` and ends with exactly one line: `CROSS-REVIEW (claude): PASS` or `CROSS-REVIEW (codex): FAIL` (the reviewer's name, then its verdict).
- It covers the PR's head commit only. A new commit needs a new review.
- A FAIL lists each finding with `file:line`, what goes wrong, and a concrete failure scenario. A PASS still names the riskiest part of the change and why it holds.
- The reviewer challenges the change and does not just check it. Ask: does it solve the stated problem, could it be smaller, which rule (AGENTS.md) or ADR does it touch, and what breaks first in production?
- The author answers every finding: fixed (with the commit), or disputed (with the reason). If the two agents still disagree, both state their positions in the PR and the owner decides. Neither agent overrides the other.

Cross-review adds to the checks; it replaces none of them. CI still runs, the factory still reviews when asked, and ADR 0005 still holds: the factory's loop merges a product PR that passes, and a person merges every factory PR.

## Talking to each other

- Signal with a short `herdr agent prompt <pane or name> "..."` that points to a PR, issue or commit. Find the other agent with `herdr agent list`.
- Send only when the other agent is `idle` or `done`. Never interrupt a turn, and never answer the other agent's approval or question dialog.
- Put the substance (findings, decisions, plans) on GitHub, where the owner can see it, not in prompts.
- Tell the other agent before you change a shared root file or something it depends on: a contract, a shared workflow, or a deploy path.

## Spend

AGENTS.md rule 12 applies to both agents. Neither adds the `agent-review` label, dispatches a paid workflow or re-enables a paused agent workflow unless the owner asks. Cross-review in our own sessions starts no paid factory run, but it does use the owner's plan limits, so keep reviews proportionate to the change. Push in batches, since every push runs CI.

## What stays with the owner

- Merging factory PRs, approving prod deploys, and any decision recorded in an ADR.
- Settling disagreements between the agents.
- Turning agents, budgets and paid workflows on or off.
