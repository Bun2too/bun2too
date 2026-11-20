#!/usr/bin/env bash
# Runs a command that executes PR or dependency code (installs) before a factory agent starts
# (AGENTS.md rule 11). Run it after factory-lockdown, so the command has no sudo.
#   contained.sh <writable-dir>... -- <command> [args...]
# The command sees the whole filesystem read-only, apart from the directories named, and a
# private /tmp. So it cannot change what later steps run (the factory's actions, downloaded
# actions, the runner's GITHUB_ENV and GITHUB_PATH files) or plant a file the agent step
# would load. It gets its own PID namespace, so everything it starts is killed when it exits
# and nothing is left behind to read the agent's environment. Network is as usual.
set -euo pipefail
args=(--ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --unshare-pid --die-with-parent --new-session)
while [ "$#" -gt 0 ] && [ "$1" != -- ]; do
  mkdir -p "$1"
  args+=(--bind "$1" "$1")
  shift
done
[ "${1:-}" = -- ] || { echo "usage: contained.sh <writable-dir>... -- <command>" >&2; exit 2; }
shift
unset GITHUB_ENV GITHUB_PATH GITHUB_OUTPUT GITHUB_STATE GITHUB_STEP_SUMMARY
exec bwrap "${args[@]}" -- "$@"
