#!/usr/bin/env bash
# Wait for the other lead agent's cross-review of one exact commit, then print the verdict
# and the comment's link (docs/agents/collaboration.md, "Review handoff").
#   scripts/wait-review.sh <pr number> <full head sha> [poll seconds, default 60]
# Run it in the background right after you ask for a review, so the verdict reaches you
# even if the herdr prompt does not. Exits 0 on PASS, 1 on FAIL, 3 if the PR's head moved
# past the commit under review (a new commit needs a new review).
set -euo pipefail

[ $# -ge 2 ] || { echo "usage: $0 <pr> <sha> [poll seconds]" >&2; exit 2; }
pr=$1 sha=$2 poll=${3:-60}
repo=${GH_REPO:-Bun2too/bun2too}

while :; do
  head=$(gh pr view "$pr" -R "$repo" --json headRefOid --jq .headRefOid)
  if [ "$head" != "$sha" ]; then
    echo "PR #$pr moved to $head; the review of $sha no longer applies."
    exit 3
  fi
  verdict=$(gh api --paginate "repos/$repo/issues/$pr/comments" --jq \
    ".[] | select(.body | startswith(\"Reviewed commit: $sha\")) |
      select(.body | test(\"CROSS-REVIEW \\\\([a-z]+\\\\): (PASS|FAIL)\\\\s*$\")) |
      \"\(.body | capture(\"CROSS-REVIEW \\\\((?<who>[a-z]+)\\\\): (?<v>PASS|FAIL)\\\\s*$\") | \"\(.who) \(.v)\") \(.html_url)\"" |
    tail -1)
  if [ -n "$verdict" ]; then
    echo "PR #$pr at $sha: $verdict"
    case "$verdict" in *" PASS "*) exit 0 ;; *) exit 1 ;; esac
  fi
  sleep "$poll"
done
