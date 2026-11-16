# 0003. Trunk-based development with environment promotion

- Status: accepted
- Date: 2026-11-16

## Context

The website and crew repos map branches to environments (`dev`, `qa`, `main`). Changes then wait on merges between branches, and the branches drift. Agent runs produce many small PRs. These are safest when they land on one trunk quickly and get promoted by the pipeline.

## Decision

- `main` is the trunk. Short-lived branches and squash merges, with flags for unfinished work.
- Environments are deploy targets. For the support agent, a merge deploys to dev, then qa, then waits for human approval before prod. This runs in `.github/workflows/deploy-support.yml`.
- Rollback redeploys an earlier SHA through the same workflow.

## Consequences

- No merge-forward between environment branches, and each change has one record of what reached each environment.
- Prod approval is the human gate, kept in a GitHub environment rather than a branch.
- Follow-up: move the website and crew pipelines to the same promotion model. Until then, their mirrors keep the branch mapping, and subtree sync to them stays manual.
