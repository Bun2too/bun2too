#!/usr/bin/env bash
# Upload this product's source to one Railway service in one environment, then
# wait for that exact deployment to succeed. Never retries an upload.
#   railway-up.sh <service> <environment>     upload and wait
#   railway-up.sh --wait-for <deployment-id>  only observe an existing deployment
# Needs RAILWAY_API_TOKEN (account or workspace token) and, to upload, RAILWAY_PROJECT_ID.
set -euo pipefail
unset RAILWAY_TOKEN
: "${RAILWAY_API_TOKEN:?RAILWAY_API_TOKEN is required}"
product_dir=$(cd "$(dirname "$0")/../.." && pwd)

status_of() {
  curl -fsS https://backboard.railway.com/graphql/v2 \
    -H "Authorization: Bearer $RAILWAY_API_TOKEN" -H 'content-type: application/json' \
    -d "$(jq -n --arg id "$1" '{query:"query($id: String!) { deployment(id: $id) { id status } }", variables:{id:$id}}')" \
    | jq -r --arg id "$1" 'if .errors or .data.deployment.id != $id then "UNREADABLE" else .data.deployment.status end'
}

# Where to read why a deployment failed. The repo is public and so are its Actions
# logs, so this prints only a link to the deployment in Railway (IDs only), never
# Railway's build or runtime log: those can carry case text or credentials.
show_link() {
  curl -fsS https://backboard.railway.com/graphql/v2 \
    -H "Authorization: Bearer $RAILWAY_API_TOKEN" -H 'content-type: application/json' \
    -d "$(jq -n --arg id "$1" '{query:"query($id: String!) { deployment(id: $id) { id projectId serviceId environmentId } }", variables:{id:$id}}')" \
    | jq -r '.data.deployment // empty
      | "Logs (Railway sign-in): https://railway.com/project/\(.projectId)/service/\(.serviceId)?environmentId=\(.environmentId)&id=\(.id)"' \
    || true
}

wait_for() {
  local id=$1 status=UNKNOWN
  for attempt in $(seq 1 40); do
    status=$(status_of "$id")
    echo "deployment $id: check $attempt/40 status=$status"
    case "$status" in
      SUCCESS) return 0 ;;
      FAILED | CRASHED | REMOVED | SKIPPED | CANCELED | CANCELLED | UNREADABLE)
        echo "::error::deployment $id ended as $status" >&2
        show_link "$id"
        return 1 ;;
    esac
    sleep 15
  done
  echo "::error::deployment $id still $status after 10 minutes; inspect it before rerunning (no new upload was made)" >&2
  return 1
}

if [ "${1:-}" = "--wait-for" ]; then
  wait_for "${2:?deployment id required}"
  exit
fi

service=${1:?usage: railway-up.sh <service> <environment>}
environment=${2:?usage: railway-up.sh <service> <environment>}
: "${RAILWAY_PROJECT_ID:?RAILWAY_PROJECT_ID is required}"
message="${GITHUB_SHA:-$(git -C "$product_dir" rev-parse HEAD)}"

out=$(railway up "$product_dir" --path-as-root --project "$RAILWAY_PROJECT_ID" \
  --environment "$environment" --service "$service" --detach --json --message "$message")
id=$(jq -r '.deploymentId // empty' <<<"$out")
[ -n "$id" ] || { echo "::error::railway up returned no deployment id" >&2; exit 1; }
echo "uploaded $service to $environment at $message: deployment $id"
[ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "- \`$service\` → \`$environment\`: deployment \`$id\` at \`$message\`" >>"$GITHUB_STEP_SUMMARY"
wait_for "$id"
