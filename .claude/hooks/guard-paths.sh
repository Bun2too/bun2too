#!/usr/bin/env bash
set -euo pipefail
path=$(jq -r '.tool_input.file_path // empty')
case "$path" in
  "" | */.env.example | */.env.sample | */.env.template) exit 0 ;;
  */.env | */.env.* | */.secrets/* | *.tfvars)
    echo "Blocked: $path holds secrets. Edit the matching .example file instead." >&2; exit 2 ;;
  */pnpm-lock.yaml | */uv.lock | */package-lock.json | */.terraform.lock.hcl)
    echo "Blocked: lockfiles change only through their package manager or terraform init." >&2; exit 2 ;;
  */bun2too-support-agent/packages/contracts/schema/*.json)
    echo "Blocked: generated file. Edit packages/contracts/src and run pnpm contracts:export." >&2; exit 2 ;;
esac
exit 0
