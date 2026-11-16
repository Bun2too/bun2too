#!/usr/bin/env bash
set -euo pipefail
path=$(jq -r '.tool_input.file_path // empty')
case "$path" in
  "" | */.env.example) exit 0 ;;
  */.env | */.env.* | */.secrets/*)
    echo "Blocked: $path holds secrets. Edit .env.example instead." >&2; exit 2 ;;
  */pnpm-lock.yaml | */uv.lock)
    echo "Blocked: lockfiles change only through pnpm install or uv lock." >&2; exit 2 ;;
  */packages/contracts/schema/*.json)
    echo "Blocked: generated file. Edit packages/contracts/src and run pnpm contracts:export." >&2; exit 2 ;;
esac
exit 0
