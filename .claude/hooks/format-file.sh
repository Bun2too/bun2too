#!/usr/bin/env bash
# Formats only inside products whose dependencies are already installed, so an
# edit never creates node_modules or .venv in a synced folder as a side effect.
set -uo pipefail
path=$(jq -r '.tool_input.file_path // empty')
[ -z "$path" ] || [ ! -f "$path" ] && exit 0
support="$CLAUDE_PROJECT_DIR/bun2too-support-agent"
case "$path" in
  "$support"/*.ts|"$support"/*.tsx|"$support"/*.js|"$support"/*.mjs|"$support"/*.json)
    [ -d "$support/node_modules" ] && (cd "$support" && pnpm exec biome check --write --no-errors-on-unmatched "$path" >/dev/null 2>&1) ;;
  "$support"/*.py)
    if [ -d "$support/services/agents/.venv" ]; then
      uv run --no-sync --directory "$support/services/agents" ruff format "$path" >/dev/null 2>&1
      uv run --no-sync --directory "$support/services/agents" ruff check --fix "$path" >/dev/null 2>&1
    fi ;;
  *.tf)
    command -v terraform >/dev/null && terraform fmt "$path" >/dev/null 2>&1 ;;
esac
exit 0
