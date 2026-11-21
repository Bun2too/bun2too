# SOP: trunk-based development

`main` is the only long-lived branch in the monorepo. Every deployable artifact is built from a commit on `main`.

## Daily flow

1. Branch from fresh `main`: `git switch -c <type>/<short-name>` (agents use `agent/issue-<n>`).
2. Keep the branch under a day and the diff under about 400 lines. Split bigger work with `/plan`.
3. Commit one product per commit (`feat(support-agent): ...`, `fix(crew-team): ...`, `docs(root): ...`).
4. Open a PR early. CI runs only the jobs for the products the PR touches.
5. Under [ADR 0005](../adr/0005-factory-review-loop-merges-product-prs.md), the factory loop or a lead agent rebase-merges a PR, factory PRs included, only after green `ci` and a passing review on the exact head commit. Keep linear history; delete the branch after merge.
6. Merging to `main` deploys the support agent to **dev**, then **qa**, then waits for a person to approve **prod**. See [environments and release](environments-and-release.md).

## Unfinished work

Unfinished work merges dark. Hide it behind a tenant config field or an environment variable that defaults to off. Never keep a branch alive to hide it. Remove the flag in a follow-up once the work ships.

## Branch protection on `main` (a person sets this up once)

- Require a PR and the `ci` status check. Every PR uses the exact-head review/merge gate, as [ADR 0005](../adr/0005-factory-review-loop-merges-product-prs.md) specifies. Its accepted decision supersedes the former blanket one-approval rule.
- Require linear history; the factory loop uses rebase merging.
- Block force-push and deletion.
- Restrict pushes to `.github/` with CODEOWNERS.

## Hotfixes

There are no release branches. Fix on a short branch, merge to `main`, and let the pipeline promote it. If prod is broken and the fix is not ready, roll back first (see [environments and release](environments-and-release.md#rollback)).

## Legacy products

`bun2too-website` and `bun2too-crew-team` still have branch-mapped pipelines (`dev`, `qa`, `main`) in their mirror repos. Inside the monorepo they follow this SOP. Their mirrors receive `main` through [subtree sync](subtrees.md). Moving their deploys to trunk-plus-promotion is a follow-up, recorded in [ADR 0003](../adr/0003-trunk-based-development.md).
