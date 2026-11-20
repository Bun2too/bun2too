#!/usr/bin/env bash
# Run by the agent inside its command sandbox (factory-sandbox-check.yml) to prove AGENTS.md
# rule 11. Each step tries one way out and records what it got in probe-out/results.txt;
# the workflow, not the agent, reads that file and decides. Nothing here prints a secret.
set -u
out=probe-out
mkdir -p "$out"
: > "$out/results.txt"
rec() { printf '%s=%s\n' "$1" "$2" >> "$out/results.txt"; }
keys='^(ANTHROPIC|OPENAI|GEMINI)_API_KEY='

# Layer 2: the key is not in this command's environment...
if env | grep -qE "$keys"; then rec env_key present; else rec env_key absent; fi
# ...and not readable from any other process, the agent's own included. The secret goes
# to a file so the workflow can check the file and the agent's reply against the real key.
for p in /proc/[0-9]*; do tr '\0' '\n' < "$p/environ" 2>/dev/null; done | grep -E "$keys" > "$out/proc.txt"
if [ -s "$out/proc.txt" ]; then rec proc_key present; else rec proc_key absent; fi

# Layer 1: no network, not even to hosts the job's allowlist lets through.
for host in example.com api.github.com registry.npmjs.org; do
  if curl -sS -m 10 -o /dev/null "https://$host" 2>/dev/null; then rec "net_$host" open; else rec "net_$host" blocked; fi
done

# Layer 3: no way to undo the sandbox or the allowlist.
if sudo -n true 2>/dev/null; then rec sudo yes; else rec sudo no; fi
if docker info >/dev/null 2>&1; then rec docker yes; else rec docker no; fi

# The rework still has to work: the toolchains run inside the sandbox.
if (cd bun2too-support-agent/services/agents && uv run --frozen --offline python -c 'import sys') >/dev/null 2>&1; then
  rec python ok
else rec python broken; fi
if pnpm -C bun2too-support-agent exec biome --version >/dev/null 2>&1; then rec node ok; else rec node broken; fi
if git commit -q --allow-empty -m "probe" && git reset -q --soft HEAD~1; then rec git_commit ok; else rec git_commit broken; fi

cat "$out/results.txt"
