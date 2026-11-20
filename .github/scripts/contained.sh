#!/usr/bin/env bash
# Runs a command that executes PR or dependency code (installs) before a factory agent starts
# (AGENTS.md rule 11). The command gets its own PID namespace: it cannot see the agent's
# processes later, and everything it starts is killed when it exits, so no install script
# can leave a process behind to read the agent's environment. Run after factory-lockdown,
# so it also has no sudo. Network and files are as usual: installs need both.
set -euo pipefail
exec bwrap --dev-bind / / --proc /proc --unshare-pid --die-with-parent --new-session -- "$@"
