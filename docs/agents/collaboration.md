# Lead agents: how Claude and Codex work together

Two lead agents build Bun2too with the owner: **Claude** (Claude Code) and **Codex**. They run side by side in a [herdr](https://herdr.dev) workspace. Each owns part of the monorepo, works only in its own checkout, and reviews the other's work before a person acts on it. Neither replaces the owner's judgement, CI or the factory's review. This page is the protocol; AGENTS.md rule 13 points here.

## Ownership

| Area                                                                                                 | Owner  |
| ---------------------------------------------------------------------------------------------------- | ------ |
| `bun2too-website/`, `bun2too-crew-team/`                                                             | Codex  |
| `bun2too-support-agent/`                                                                             | Claude |
| The factory: `.github/`, `.claude/`, `docs/factory.md`, `docs/sdlc.md`, `docs/adr/`                  | Claude |
| Shared root files: `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/agents/`, `docs/sop/`, `docs/specs/` | Both   |

The owner of an area decides how it changes. Either agent may change a shared root file, but only in a PR the other has reviewed. An agent that needs a change in the other's area asks for it (an issue or a prompt) instead of making it. The exception is a one-line fix that blocks its own work, which then goes in a PR the area's owner reviews.

## Your GitHub identity

AGENTS.md rule 15. Each lead agent has its own GitHub App, installed on every Bun2too repository:

| Agent  | Acts as               | App ID  | Private key (owner-managed, outside the repo) |
| ------ | --------------------- | ------- | --------------------------------------------- |
| Claude | `bun2too-claude[bot]` | 5868181 | `~/.config/bun2too/agents/claude.pem`         |
| Codex  | `bun2too-codex[bot]`  | 5868247 | `~/.config/bun2too/agents/codex.pem`          |

- **Every GitHub write goes through the helper:** `scripts/as-agent.sh <claude|codex> <command> [args...]`. For that one command it mints a one-hour installation token and hands it to `gh` (`GH_TOKEN`) and to git (credentials, with SSH remotes rewritten to HTTPS). It also sets the git author and committer to the bot. Examples:

  ```sh
  scripts/as-agent.sh claude git commit -m "fix(root): ..."
  scripts/as-agent.sh claude git push origin HEAD:fix/topic
  scripts/as-agent.sh claude gh pr create --base main --title "..." --body-file body.md
  scripts/as-agent.sh claude gh pr comment 19 --body-file review.md
  scripts/as-agent.sh claude gh pr merge 19 --rebase --match-head-commit <sha>
  ```

  Run `git commit` through it too, or the commit is authored by the owner's git identity. Reads (`gh pr view`, `gh run view`, `git fetch`) may use either identity.

- **Why:** the actor of a merge is the actor of the deploy run it starts. With the bot as actor, the owner is not approving their own run, so `support-prod`'s self-review prevention stays on and the owner can approve. The audit trail also shows which agent did what.
- **Keys:** use only your own key, and never read, copy or print the other agent's. Never print a token, and never put one in a command line, a file or a comment. Both keys sit under one OS account, so this is a rule the agents keep, not something the machine enforces.
- **When the helper fails** (no key, a refused token, a missing permission), stop and tell the owner. Do not fall back to the owner's `gh` login or SSH key for a write.
- **Permissions** (owner-managed in each app's settings): contents, pull requests, issues and workflows (write); actions and checks (read). `gh workflow run` (a manual deploy or rollback) also needs actions (write). Without it, the owner dispatches those runs.

## One checkout each

- Each agent works in its own checkout or `git worktree`, on its own local branches: `claude/*` and `codex/*`. Neither rebases or switches the other's branch or touches the other's uncommitted files. Both may push to an open PR's branch, taking turns as described under [One PR per feature](#one-pr-per-feature). AGENTS.md rule 6 applies between the agents as it does to people.
- Before editing, run `git status --short` and `git branch --show-current` in your own checkout.
- Where a branch starts: work that continues an open PR starts from that PR's head commit; work for a new PR starts from `origin/main`. Never start a new PR from another open PR's branch.
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

### Review handoff

A passed PR must not sit waiting for someone to notice. On 2026-11-21 PRs #19 and #20 had PASS and green CI, but the herdr prompt saying so never started a turn for the author, so the owner had to chase both agents.

- **The author watches GitHub, not the pane.** Right after asking for a review, the author runs `scripts/wait-review.sh <pr> <full head sha>` in the background. It polls the PR, and exits with the verdict and the comment's link as soon as a `Reviewed commit: <sha>` comment lands (0 PASS, 1 FAIL, 3 if the head moved).
- **The author merges on PASS.** On a PASS with green `ci` and a clean merge state, the PR's author merges it right away (`scripts/as-agent.sh <you> gh pr merge <n> --rebase --match-head-commit <sha>`). It doesn't wait for the owner or for a second signal. If the author is mid-task for long, the reviewer may merge instead and says so on the PR.
- **On FAIL, the author fixes it first.** The fix comes before new work, then the author asks for a review of the new head and starts a new `wait-review.sh`.
- **The reviewer still signals.** After posting the verdict, the reviewer tells the author with `scripts/agent-tell.sh <author> "..."`: the verdict and the comment link.
- **If GitHub fails, the verdict still travels.** A reviewer who cannot post sends the full verdict through `agent-tell.sh`: the exact head SHA, PASS or FAIL, and the findings. The author posts it on the PR as a quoted relay, credited to the reviewer, and merges on it as usual. The reviewer replaces the relay with its own comment once it can.

## Never go silent

On 2026-11-22 Codex could not reach api.github.com while reviewing the deploy fixes. It stopped without telling Claude, who sat waiting for a verdict. Asked by the owner, it said it had no way to message Claude, after many rounds of doing exactly that in the same session. Both are failures, and these rules exist so neither happens again.

1. **A blocker is a message, not a stop.** When a tool, network call, PR lookup, credential or permission fails, finish the turn by telling the other agent (`scripts/agent-tell.sh`) and the owner (your reply): what failed, with the exact error, what you tried, and what you need. Never just end the turn.
2. **Check before you say "I can't".** Before telling anyone you cannot message the other agent, reach GitHub or find a PR, read this file and try it. `scripts/agent-tell.sh` always works while both agents run in herdr; it exits non-zero and says why when it does not. `gh pr list -R Bun2too/bun2too` finds every open PR. A claim of incapacity that a command would have disproved is a false statement.
3. **Every handoff is closed.** A review request gets a verdict or a blocker report. A blocker report gets an answer. Whoever ends a turn with work waiting on the other agent says so to that agent before stopping.
4. **One failure is not a dead end.** Retry once. Then take the fallback: GitHub down → `agent-tell.sh`; herdr down → a PR comment; both down → tell the owner. Name the fallback you used.
5. **Check open PRs before you end a turn.** Run `gh pr list -R Bun2too/bun2too`. Any open PR by the other agent without your verdict at its current head is yours to review now; any PR of yours with a PASS, green `ci` and a clean merge state is yours to merge now. On 2026-11-22 #27 waited because its review request was only a PR comment and the reviewer never looked.
6. **Relay what the owner says.** When the owner tells you something that affects the other agent's work, pass it on with `agent-tell.sh`.

## Talking to each other

- Signal with `scripts/agent-tell.sh <claude|codex> "..."`, a short message that points to a PR, issue or commit. It finds the other agent's pane by name in `herdr agent list`, waits until that agent is idle, and succeeds only when the message starts a turn. Use raw `herdr agent prompt <pane> "..." --wait --until working --timeout 30000` only if the script itself is broken, and say so.
- **A prompt counts only once it starts a turn.** `herdr agent prompt` can report success while the text sits unsent in the other agent's input box, or mixes into what the owner is typing. With `--wait --until working`, a prompt that doesn't start a turn within 30 seconds fails. Then post the same message as a PR comment, and try the prompt again once the other agent is idle. The GitHub comment and `wait-review.sh` stay the reliable path.
- Send only when the other agent is `idle` or `done`. Never interrupt a turn, and never answer the other agent's approval or question dialog.
- Put the substance (findings, decisions, plans) on GitHub, where the owner can see it, not in prompts.
- Tell the other agent before you change a shared root file or something it depends on: a contract, a shared workflow, or a deploy path.

## Spend

AGENTS.md rule 12 applies to both agents. Neither adds the `agent-review` label, dispatches a paid workflow or re-enables a paused agent workflow unless the owner asks. Cross-review in our own sessions starts no paid factory run, but it does use the owner's plan limits, so keep reviews proportionate to the change. Push in batches, since every push runs CI.

## What stays with the owner

- Approving prod deploys, PRs that grant a new write permission, and any decision recorded in an ADR.
- The agents' GitHub Apps: their permissions, installations and private keys.
- Settling disagreements between the agents.
- Turning agents, budgets and paid workflows on or off.
