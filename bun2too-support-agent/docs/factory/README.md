# The Relay factory

Relay is built by a software factory: agents turn tickets and PRs into merged code, and people review finished work and unresolved problems. Vocabulary follows Matt Pocock's `software-factory` skill (task, trigger, run, runner, brake). Rigor follows Lauren Tan's pstack principles.

## Services

| Slot                   | Product                                                                                  |
| ---------------------- | ---------------------------------------------------------------------------------------- |
| Ticket tracker         | GitHub Issues (labels in `docs/agents/triage-labels.md`)                                 |
| Ticket source          | Humans; `relay.factory.failed_run` alerts; nightly eval regressions                      |
| Git host               | GitHub                                                                                   |
| Orchestrator           | GitHub Actions                                                                           |
| Runner                 | GitHub-hosted Actions runners (disposable)                                               |
| Observability platform | Actions run pages + the PR body evidence. Product traces stay in Relay's own OTel stack. |

## Tasks

Each task answers the five design questions: trigger, what it does, what it triggers next, where a human re-enters, and what stops two runs doing the same work.

| Task          | Trigger                                             | Does                                                                                                                          | Next             | Human re-entry                                 | Dedupe                                       |
| ------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ---------------- | ---------------------------------------------- | -------------------------------------------- |
| **Explore**   | issue labelled `needs-triage`                       | checks claims against code, reproduces, labels `ready-for-agent`, `needs-info` or `ready-for-human`; never pushes             | Implement        | `ready-for-human`                              | concurrency group per issue                  |
| **Implement** | issue labelled `ready-for-agent`                    | `/tdd` until `pnpm check` passes; opens a draft PR linked to the issue                                                        | Review           | none until review passes                       | one branch per issue: `agent/issue-<n>`      |
| **Review**    | PR opened, synchronized, or labelled `agent-review` | `/code-review` against the merge base: Standards and Spec sub-agents in fresh contexts; posts one comment with a verdict line | Rework on `FAIL` | on `PASS`, the PR waits for a human merge      | concurrency group per PR, cancel in progress |
| **Rework**    | review comment with `VERDICT: FAIL`                 | fixes only the named findings, runs `pnpm check`, commits as the bot, pushes                                                  | Review           | 3 failed rounds: label `ready-for-human`, stop | round counter in PR labels `rework-1..3`     |
| **Hygiene**   | any push to a PR branch                             | `pnpm fix`; commits formatting/lint fixes if any                                                                              | CI               | never                                          | skips when the last commit is its own        |
| **Ratchet**   | daily 06:00 UTC                                     | removes one path from `docs/factory/ratchet.txt`, fixes it under the stricter rule, opens a PR                                | Review           | human merge                                    | one open ratchet PR at a time                |
| **Retro**     | 1 in 10 merged PRs                                  | reads the PR, its reviews and runs; proposes edits to rules or skills as a PR                                                 | Review           | human merge, always                            | one open retro PR at a time                  |

## Brakes

1. **Automated checks:** `pnpm check` (Biome, tsc, Vitest, Ruff, mypy, pytest, contract drift) and, for prompt changes, `pnpm eval`.
2. **Automated review:** a separate run with no memory of the implementation, reading the diff cold.
3. **Human review:** a person merges every PR. What they catch becomes a new check (see `enforcement.md`) or a sharper review rule.

Start slow: the Implement trigger is manual (`ready-for-agent` is applied by a human) until ten consecutive agent PRs merge without human rework. Then let Explore apply it.

## Spend and safety

- Each agent workflow sets `timeout-minutes` and a turn cap.
- Agent runs use a token with `contents: write`, `pull-requests: write`, `issues: write` only. They cannot change workflows (`.github/` is protected by CODEOWNERS and branch rules).
- Fix runs that touch the factory itself (`.claude/`, `.cursor/`, `.github/`, `AGENTS.md`, `docs/factory/`) are never auto-merged and never chained.
