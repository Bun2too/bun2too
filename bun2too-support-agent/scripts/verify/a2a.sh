#!/usr/bin/env bash
set -euo pipefail
message=${1:?usage: a2a.sh <message>}
gateway=${RELAY_GATEWAY:-http://localhost:8787}
key=${RELAY_TENANT_KEY:-dev-bun2too-key}
out=".verify/$(date -u +%Y%m%dT%H%M%SZ)-a2a-$$"
mkdir -p "$out"

curl -fsS "$gateway/.well-known/agent-card.json" > "$out/agent-card.json"
send=$(jq -n --arg m "$message" --arg id "msg-$(date +%s%N)" \
  '{jsonrpc:"2.0", id:1, method:"message/send", params:{message:{role:"user", messageId:$id, parts:[{kind:"text", text:$m}]}}}')
curl -fsS -X POST "$gateway/a2a" -H "x-api-key: $key" -H 'content-type: application/json' -d "$send" > "$out/send.json"
task_id=$(jq -r .result.id "$out/send.json")
sleep 2
get=$(jq -n --arg id "$task_id" '{jsonrpc:"2.0", id:2, method:"tasks/get", params:{id:$id}}')
curl -fsS -X POST "$gateway/a2a" -H "x-api-key: $key" -H 'content-type: application/json' -d "$get" > "$out/get.json"
echo "task $task_id -> $(jq -r .result.status.state "$out/get.json") / relay $(jq -r .result.metadata.relayStatus "$out/get.json") (evidence: $out)"
