#!/usr/bin/env bash
set -euo pipefail
message=${1:?usage: intake.sh <message> [channel]}
channel=${2:-web_widget}
gateway=${RELAY_GATEWAY:-http://localhost:8787}
key=${RELAY_TENANT_KEY:-dev-bun2too-key}
idem=${RELAY_IDEMPOTENCY_KEY:-verify-$(date +%s%N)}
out=".verify/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$out"

body=$(jq -n --arg m "$message" --arg c "$channel" '{channel:$c, message:$m}')
curl -fsS -X POST "$gateway/v1/intake" -H "x-api-key: $key" -H "idempotency-key: $idem" \
  -H 'content-type: application/json' -d "$body" > "$out/intake.json"
case_id=$(jq -r .caseId "$out/intake.json")
jq -r .traceId "$out/intake.json" > "$out/trace_id.txt"

for _ in $(seq 1 30); do
  curl -fsS "$gateway/v1/cases/$case_id" -H "x-api-key: $key" > "$out/case.json"
  status=$(jq -r .status "$out/case.json")
  case "$status" in resolved|escalated|awaiting_customer|rejected) break ;; esac
  sleep 1
done
curl -fsS "$gateway/v1/cases/$case_id/events" -H "x-api-key: $key" \
  | sed -n 's/^data: //p' | jq -s . > "$out/events.json"

echo "case $case_id -> $status (evidence: $out)"
# The exception class of a failed run, never its message: these logs are public.
jq -c '.[] | {seq, status, actor, reason} + (if .data.error then {error: .data.error} else {} end)' "$out/events.json"
case "$status" in resolved|escalated|awaiting_customer|rejected) exit 0 ;; *) exit 1 ;; esac
