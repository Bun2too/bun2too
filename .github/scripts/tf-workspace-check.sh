#!/usr/bin/env bash
# Read-only check before `terraform init`, against the HCP Terraform API.
#   tf-workspace-check.sh <workspace>
# The workspace must exist and use Local execution: runs happen in this job, which passes
# the TF_VAR_* inputs. A workspace in Remote execution runs on HCP's agents without them,
# and its apply fails with "Failed to create configuration version".
# On a miss it lists the workspace names and execution modes this token can see. It never
# prints the token or a response body.
# Needs TF_TOKEN and TF_CLOUD_ORGANIZATION.
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: $0 <workspace>" >&2; exit 2; }
ws=$1
[ -n "${TF_CLOUD_ORGANIZATION:-}" ] ||
  { echo "::error::TF_CLOUD_ORGANIZATION is empty. Set it as a variable on this GitHub environment."; exit 1; }
[ -n "${TF_TOKEN:-}" ] ||
  { echo "::error::TF_API_TOKEN is empty. Set it as a secret on this GitHub environment."; exit 1; }

out=$(mktemp)
trap 'rm -f "$out"' EXIT

# The header goes in on stdin (printf is a shell builtin), so the token is never in any
# process's argv, where another process on the runner could read it.
api() {
  printf 'Authorization: Bearer %s\n' "$TF_TOKEN" |
    curl -s -o "$out" -w '%{http_code}' --max-time 30 -H @- \
      -H "Content-Type: application/vnd.api+json" "https://app.terraform.io/api/v2/$1"
}

list_visible() {
  if [ "$(api "organizations/$TF_CLOUD_ORGANIZATION/workspaces?page%5Bsize%5D=100")" = 200 ]; then
    echo "Workspaces this token can see in $TF_CLOUD_ORGANIZATION:"
    jq -r '.data[] | "  \(.attributes.name) (\(.attributes["execution-mode"]) execution)"' "$out"
  else
    echo "This token cannot list workspaces in $TF_CLOUD_ORGANIZATION either."
  fi
}

# An empty or odd name would turn the URL into the list endpoint or another path.
if ! [[ "$ws" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "::error::Workspace name '$ws' is empty or not a valid HCP Terraform workspace name."
  exit 1
fi
code=$(api "organizations/$TF_CLOUD_ORGANIZATION/workspaces/$ws")
echo "$ws: HTTP $code"
if [ "$code" != 200 ]; then
  echo "::error::The token in this environment cannot see workspace $ws in organization $TF_CLOUD_ORGANIZATION (HTTP $code). Create it, or give the token's team access to it."
  list_visible
  exit 1
fi
mode=$(jq -r '.data.attributes["execution-mode"] // ""' "$out")
echo "$ws: execution mode $mode"
if [ "$mode" != local ]; then
  echo "::error::Set workspace $ws to Local execution (Settings > General > Execution Mode). This job runs Terraform itself and passes its inputs."
  exit 1
fi
