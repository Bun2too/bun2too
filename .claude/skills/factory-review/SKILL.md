---
name: factory-review
description: Run the factory's automated review on a PR or branch in any Bun2too product. Addy Osmani's code-reviewer and security-auditor plus the shared spec-reviewer run in parallel fresh contexts, then one comment is posted ending in a machine-readable verdict. Used by the agent-review workflow; also run it locally before opening a PR.
---

# Factory review

1. Pin the base with `git merge-base origin/main HEAD`. Fail early if the diff is empty. List the products the diff touches (top-level folders) and read each one's `AGENTS.md`.
2. Spawn three subagents in parallel, each with a fresh context, the diff command and the products' `AGENTS.md` paths:
   - `code-reviewer` (Addy's persona): five axes (correctness, readability, architecture, security, performance), judged against the product's coding standards. It must end with `CODE: PASS` or `CODE: FAIL (<n>)`, where only Critical and Important findings count.
   - `security-auditor` (Addy's persona): only if the diff touches auth, input parsing, prompts, secrets, infra, CI or dependencies. It must end with `SECURITY: PASS` or `SECURITY: FAIL (<n>)`. Otherwise record `SECURITY: SKIPPED`.
   - `spec-reviewer` (shared agent): must end with `SPEC: PASS`, `SPEC: FAIL (<n>)` or `SPEC: SKIPPED (no spec)`.

   If `code-reviewer` or `security-auditor` is not installed (CI runners do not install plugins), spawn a `general-purpose` subagent in its place. Brief it with the persona's role as described above and the same closing line. Say in that section that the fallback was used.
3. Do not merge or rerank their findings. Post one PR comment. Its first line is `Reviewed commit: <head sha>` (the workflow gives the head commit; locally use `git rev-parse HEAD`). Then come three sections, `## Code`, `## Security` and `## Spec`, each pasted verbatim.
4. The comment's last line is the verdict, exactly one of:
   - `VERDICT: PASS`: every reviewer finished and none reported FAIL.
   - `VERDICT: FAIL`: any reviewer reported FAIL.
   - `VERDICT: INCONCLUSIVE`: no reviewer reported FAIL, but one could not finish. Its section says why (for example, the subagent errored). A person decides; no rework starts.

Always post the comment, even when reviewers fail; a review that ends without a comment leaves the PR with no signal. The workflow checks for the `Reviewed commit:` line and reports a missing review on the PR.

The `agent-rework` workflow keys off that last line, so never change its format. Suggestion-level findings (for example from `code-simplification`) never fail a PR; they are listed for the person who merges.
