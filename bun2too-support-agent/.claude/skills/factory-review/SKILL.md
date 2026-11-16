---

name: factory-review
description: Run Relay's automated review on a PR or branch: Standards and Spec reviewers in parallel fresh contexts plus the comment sweeper, then post one comment ending in a machine-readable verdict. Used by the agent-review workflow; also usable locally before opening a PR.
---

# Factory review

1. Pin the base: `git merge-base origin/main HEAD`. Fail early if the diff is empty.
2. Spawn three subagents in parallel, each with a fresh context and the diff command: `standards-reviewer`, `spec-reviewer`, `comment-sweeper`.
3. Do not merge or rerank their findings. Post one PR comment with three sections, `## Standards`, `## Spec`, `## Comments`, each verbatim.
4. The comment's last line is the verdict, exactly one of:
   - `VERDICT: PASS` when Standards and Spec both pass (comment-sweeper findings alone never fail a PR; they are listed for the human).
   - `VERDICT: FAIL` otherwise.

The `agent-rework` workflow keys off that last line, so never change its format.
