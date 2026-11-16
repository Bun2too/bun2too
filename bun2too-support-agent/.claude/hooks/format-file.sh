#!/usr/bin/env bash
set -uo pipefail
path=$(jq -r '.tool_input.file_path // empty')
[ -z "$path" ] || [ ! -f "$path" ] && exit 0
cd "$CLAUDE_PROJECT_DIR"
case "$path" in
  *.ts|*.tsx|*.js|*.mjs|*.json)
    pnpm exec biome check --write --no-errors-on-unmatched "$path" >/dev/null 2>&1 || true ;;
  *.py)
    uv run --directory services/agents ruff format "$path" >/dev/null 2>&1 || true
    uv run --directory services/agents ruff check --fix "$path" >/dev/null 2>&1 || true ;;
esac
exit 0
