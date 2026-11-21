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
- Base every branch on `origin/main`, never on another open PR.
- Commit only paths you changed (`git add <paths>`, never `git add -A`).

## One PR per feature

AGENTS.md rule 14. Every open PR can start CI, a paid factory review and a cross-review, and two PRs on the same files end in a merge conflict someone has to untangle. On 2026-11-20 the two agents had four PRs open, two of them conflicting, while more finished work sat unpushed on local branches. So:

- **Check first.** Run `gh pr list`, and `gh pr view <n> --json files,headRefName` on any open PR that might overlap.
- **The PR exists: build on it.** Fetch it and base your work on its head commit (`git switch -c <you>/<topic> origin/<its branch>`, or cherry-pick your commits onto it). Commit one product per commit (rule 2), then push to the PR's branch (`git push origin HEAD:<its branch>`). Do not open another PR.
- **No PR yet: open one.** Branch from `origin/main`, then commit, push and open the PR for the feature as soon as it is complete and passes its checks locally.
- **Don't park work.** Finished work does not stay on a local branch. It goes to the open PR for its feature, or into a new one.
- **Take turns on a shared PR.** Pull right before you commit, so you never need a force-push (rule 9). Push one batch, then comment on the PR with the new head commit, so the other agent pulls before its next commit and cross-reviews it.
- **Never stack, never overlap.** No PR is based on another open PR's branch. No two open PRs touch the same file. A PR that needs another PR's changes to pass (for example a gate that the other PR adds) goes into that PR.
- **Conflicts first.** A PR that conflicts with `main` is fixed by its author before any other work. Agents don't force-push and `main` keeps a linear history, so the author asks the owner to rebase the branch, or moves its commits to a fresh branch from `origin/main` and closes the old PR in the same step.
- **Close what is dead.** A superseded or abandoned PR is closed the same day, with a link to the PR that carries its work. Stale agent PRs (no activity for 48 hours) are closed too.

## Cross-review

Every PR either agent opens is reviewed by the other before it merges, and before anyone asks the factory to review it (the `agent-review` label).

- The review is one PR comment. It starts with `Reviewed commit: <full SHA>` and ends with exactly one line: `CROSS-REVIEW (claude): PASS` or `CROSS-REVIEW (codex): FAIL` (the reviewer's name, then its verdict).
- It covers the PR's head commit only. A new commit written by either agent or a person needs a new review.
- Commits the factory's rework rounds push (as `bun2too-software-factory[bot]`) are the exception. The factory's own review and the rework guard check them (ADR 0005), and the loop may merge a product PR without a fresh cross-review. Nothing in the merge job enforces cross-review: it is a rule the agents keep. Neither agent asks for the `agent-review` label before its PR has a cross-review PASS on the current head.
- A FAIL lists each finding with `file:line`, what goes wrong, and a concrete failure scenario. A PASS still names the riskiest part of the change and why it holds.
- The reviewer challenges the change and does not just check it. Ask: does it solve the stated problem, could it be smaller, which rule (AGENTS.md) or ADR does it touch, and what breaks first in production?
- The author answers every finding: fixed (with the commit), or disputed (with the reason). If the two agents still disagree, both state their positions in the PR and the owner decides. Neither agent overrides the other.

Cross-review adds to the checks; it replaces none of them. CI still runs, the factory still reviews when asked, and ADR 0005 still holds: the factory's loop merges a PR that passes. A lead agent merges a PR (Rebase and merge) once `ci` is green and the other agent's cross-review PASS names its exact head.

## Talking to each other

- Signal with a short `herdr agent prompt <pane or name> "..."` that points to a PR, issue or commit. Find the other agent with `herdr agent list`.
- Send only when the other agent is `idle` or `done`. Never interrupt a turn, and never answer the other agent's approval or question dialog.
- Put the substance (findings, decisions, plans) on GitHub, where the owner can see it, not in prompts.
- Tell the other agent before you change a shared root file or something it depends on: a contract, a shared workflow, or a deploy path.

## Spend

AGENTS.md rule 12 applies to both agents. Neither adds the `agent-review` label, dispatches a paid workflow or re-enables a paused agent workflow unless the owner asks. Cross-review in our own sessions starts no paid factory run, but it does use the owner's plan limits, so keep reviews proportionate to the change. Push in batches, since every push runs CI.

## What stays with the owner

- Approving prod deploys, PRs that grant a new write permission, and any decision recorded in an ADR.
- Settling disagreements between the agents.
- Turning agents, budgets and paid workflows on or off.
