#!/usr/bin/env bash
# Checks the commits a Rework run made (BEFORE..HEAD) before the workflow pushes them.
# Usage: rework-guard.sh <before-sha> <allowed-scope>...
#   allowed-scope: a product folder the PR already touches (bun2too-support-agent) or "root".
# Prints one line per violation and exits 1 if there are any.
set -euo pipefail

before=$1
shift
allowed=" $* "
violations=()

scope_of() {
  case "$1" in
    bun2too-*/*) echo "${1%%/*}" ;;
    *) echo root ;;
  esac
}

for commit in $(git rev-list --reverse "$before..HEAD"); do
  scopes=$(git diff-tree --no-commit-id --name-only -r "$commit" | while read -r f; do scope_of "$f"; done | sort -u)
  [ "$(echo "$scopes" | grep -c .)" -le 1 ] ||
    violations+=("$(git log -1 --format=%h "$commit") touches more than one product: $(echo $scopes)")
done

while read -r f; do
  [ -n "$f" ] || continue
  # Agent config at any depth: a product's .claude/ or an .mcp.json could make the next
  # factory run load hooks or MCP servers outside the sandbox.
  if [[ "$f" =~ (^|/)(\.claude|\.cursor|\.github)/ || "$f" =~ (^|/)(AGENTS|CLAUDE)\.md$ || "$f" =~ (^|/)\.mcp\.json$ || "$f" == docs/factory.md || "$f" == docs/sdlc.md ]]; then
    violations+=("$f is a factory file; only a person changes those")
  elif [[ "$f" == rework-report.md || "$f" == .factory/* ]]; then
    violations+=("$f was committed; it is the run's input or report, not code")
  elif [[ "$allowed" != *" $(scope_of "$f") "* ]]; then
    violations+=("$f is outside the products this PR touches")
  fi
done < <(git diff --name-only "$before..HEAD")

# A finding is fixed, not silenced: no new suppressions, skipped tests or focused tests.
silencers='noqa|type: *ignore|pyright: *ignore|eslint-disable|biome-ignore|@ts-(ignore|expect-error|nocheck)|pragma: *no ?cover|pytest\.mark\.(skip|xfail)|\b(it|test|describe)\.(skip|only|todo)\(|\bx(it|describe)\('
while IFS= read -r line; do
  violations+=("adds a suppression or skipped test: ${line:0:160}")
done < <(git diff -U0 "$before..HEAD" | grep -E '^\+' | grep -vE '^\+\+\+ ' | grep -E "$silencers" || true)

if [ ${#violations[@]} -gt 0 ]; then
  printf -- '- %s\n' "${violations[@]}"
  exit 1
fi
