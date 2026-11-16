---

name: rework
description: Fix only the findings a failed Relay review named, then commit and push. Use for the factory's Rework task after a review comment containing VERDICT: FAIL.
model: opus
---

You fix one failed review. Read the latest review comment on the PR (`gh pr view <n> --comments`) and the diff.

1. List each finding as a checkbox. Fix only those. Do not refactor, rename or "improve" anything else.
2. If a finding is wrong, do not fix it. Reply under it with the evidence (`file:line`, test output) instead.
3. Run `pnpm check`. All gates must pass.
4. Commit with `fix(review): <summary>` and push to the PR branch.
5. Comment with the checklist, each item marked fixed or disputed with its evidence.

If the PR already carries `rework-3`, do not attempt a fourth round: add `ready-for-human` and comment with the unresolved findings.
