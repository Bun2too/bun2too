# Issue tracker: GitHub

Issues for this repo live in GitHub Issues. Use the `gh` CLI.

- Create: `gh issue create --title "<title>" --body-file <file> --label needs-triage`
- Read: `gh issue view <n> --comments`
- Label: `gh issue edit <n> --add-label ready-for-agent --remove-label needs-triage`
- Link a PR: put `Closes #<n>` in the PR body.
- Blocking edges (from `/to-tickets`): a `Blocked by #<n>` line at the top of the issue body, one per blocker.

Specs from `/to-spec` are issues labelled `spec`; their tickets reference the spec issue.

PRs as a request surface: **off**.
