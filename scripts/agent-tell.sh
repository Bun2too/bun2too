#!/usr/bin/env bash
# Deliver a short message to the other lead agent's herdr pane, found by name, and fail
# loudly if it does not start a turn (docs/agents/collaboration.md, "Never go silent").
#   scripts/agent-tell.sh <claude|codex> "<message>"
# Exits 0 once the message started a turn. Otherwise exits non-zero and says why: then put
# the same message on the PR and tell the owner in your reply. Never stop silently.
# This path always exists while both agents run in herdr: "I have no way to message the
# other agent" is not true here. Run this script before saying it.
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: $0 <claude|codex> <message>" >&2; exit 2; }
agent=$1 message=$2
case $agent in claude | codex) ;; *) echo "unknown agent: $agent" >&2; exit 2 ;; esac

fallback="Post the message on the PR and tell the owner."
# The reason herdr gave, from its JSON error or its raw output.
reason() { jq -r '.error.code // .error.message // .result.type // empty' <<<"$1" 2>/dev/null || true; }

if ! list=$(herdr agent list 2>&1); then
  why=$(reason "$list")
  echo "agent-tell: herdr agent list failed: ${why:-$(head -c 200 <<<"$list")}. $fallback" >&2
  exit 1
fi
if ! pane=$(jq -r --arg a "$agent" '[.result.agents[] | select(.agent == $a)][0].pane_id // empty' <<<"$list" 2>/dev/null); then
  echo "agent-tell: could not read herdr agent list output. $fallback" >&2
  exit 1
fi
if [ -z "$pane" ]; then
  echo "agent-tell: no $agent pane in herdr. $fallback" >&2
  exit 1
fi
[ "$pane" != "${HERDR_PANE_ID:-}" ] || { echo "agent-tell: $pane is your own pane" >&2; exit 2; }

# Never interrupt a turn, and never type into the other agent's approval dialog.
if ! waited=$(herdr agent wait "$pane" --until idle --until done --timeout 600000 2>&1); then
  why=$(reason "$waited")
  case $why in
    timeout) echo "agent-tell: $agent ($pane) was still working or blocked after 10 minutes. $fallback" >&2 ;;
    *) echo "agent-tell: herdr agent wait failed for $agent ($pane): ${why:-$(head -c 200 <<<"$waited")}. $fallback" >&2 ;;
  esac
  exit 1
fi

out=$(herdr agent prompt "$pane" "$message" --wait --until working --timeout 30000 2>&1) || true
if jq -e '.result.type == "agent_prompted" and .result.agent.agent_status == "working"' <<<"$out" >/dev/null 2>&1; then
  echo "agent-tell: delivered to $agent ($pane); it started a turn."
  exit 0
fi
why=$(reason "$out")
echo "agent-tell: not delivered to $agent ($pane): ${why:-$(head -c 200 <<<"$out")}. $fallback" >&2
exit 1
