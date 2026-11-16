---

name: add-specialist
description: Scaffold a new Relay specialist agent (prompt, tools, policy hooks, tests, eval rows) and register it. Use when a tenant needs a new intent handled, e.g. "add a warranty specialist".
---

# Add a specialist

A specialist is a deep module: one `Specialist` protocol method (`run`) hiding a prompt, a tool allow-list and output parsing.

1. Add the intent to `Intent` in `packages/contracts/src/case.ts`, run `pnpm contracts:export`, and mirror it in `services/agents/src/relay_agents/contracts.py`. Add the term to `GLOSSARY.md`.
2. Add `services/agents/src/relay_agents/prompts/<intent>.md` (copy `knowledge.md`) and register it in `PROMPT_FILES` in `specialists/__init__.py`. Tools are built from ports in `specialists/tools.py`, never from raw clients.
3. Write tools as read-only unless the ticket says otherwise. A write tool takes a `PolicyDecision` argument and must be gated in `policy.py` with a tenant-configurable threshold.
4. If the offline knowledge lookup is not a fair stand-in for the new specialist, add an offline class beside `specialists/offline.py` and use it in `build_offline_specialists`.
5. Tests first, at the seam: `tests/test_graph.py` gets one case that routes to the new specialist and one that escalates from it.
6. Add at least 10 rows to `evals/intake-golden.jsonl` with the new intent, including two adversarial ones.
7. Enable it for a tenant in `tenants/<slug>.yaml` `specialists:`.
8. `pnpm check`, then `pnpm eval` and paste before/after routing accuracy in the PR.
