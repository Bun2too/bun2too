#!/usr/bin/env bash
# Read-only smoke check of a deployed gateway. Creates no cases or tickets.
#   smoke.sh <gateway-url>
set -euo pipefail
url=${1:?usage: smoke.sh <gateway-url>}
for _ in $(seq 1 20); do curl -fsS "$url/healthz" >/dev/null 2>&1 && break; sleep 6; done
curl -fsS "$url/healthz" | jq -e '.ok == true' >/dev/null
curl -fsS "$url/.well-known/agent-card.json" | jq -e '.name and .url and (.skills | length > 0)' >/dev/null
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$url/v1/intake" -H 'content-type: application/json' -d '{}')
[ "$code" = 401 ] || { echo "::error::intake without a tenant key returned $code, expected 401" >&2; exit 1; }
echo "smoke ok: $url"
