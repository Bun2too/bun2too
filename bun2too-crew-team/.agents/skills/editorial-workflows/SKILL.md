---
name: editorial-workflows
description: Modify the marketing team's editorial roles, task dependencies, source grounding, novelty rules, or content review behavior.
---

Read `crewai_agents/AGENTS.md`, `app/crews.py`, `app/agents.json` and the affected `app/agent_context/<role>.md` files (app paths are under crewai_agents). Scheduled and manual workflows have different prompts; change the intended path only.

Use current source snapshots as evidence. Keep prior post text and artwork out of performance context; historical titles/URLs are exclusions. Keep Writer and Editor authorized to revise or replace unsuitable drafts. Tester must judge the final edited candidate, and Delivery must preserve that candidate and unresolved review findings.

Keep deterministic citation, duplicate-content, reviewer, hashing and publication-window checks. A prompt change is not proof of improved model behavior. Regression tests should reproduce the observed bad handoff or invalid artifact and show that guards remain intact. When changing stable role knowledge, update its context file; do not embed dated campaign results or full copied prompts.

Validate with `scripts/verify_marketing.py`. A live candidate still needs the configured independent reviews. Do not force approval to make a workflow appear successful.
