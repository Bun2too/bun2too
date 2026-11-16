# Issue tracker: GitHub

Issues live in GitHub Issues on the monorepo (`Bun2too/bun2too`), managed with the `gh` CLI. Mirrors do not take issues.

- Create: `gh issue create --title "<title>" --body-file <file> --label needs-triage --label area:<product>`
- Read: `gh issue view <n> --comments`
- Label: `gh issue edit <n> --add-label ready-for-agent --remove-label needs-triage`
- Link a PR: put `Closes #<n>` in the PR body.
- Blocking edges (from `/to-tickets`): one `Blocked by #<n>` line per blocker at the top of the issue body.

Specs from `/spec` are either a `SPEC.md` in the product (merged by PR) or an issue labelled `spec`. Tickets reference their spec.

PRs as a request surface: **off**.
