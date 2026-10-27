# Bun2too crew-team context

This repository runs a FastAPI/CrewAI marketing team, deterministic article/Facebook publishing, n8n schedules, and Railway/Terraform deployment. Start with the files relevant to the task; do not reconstruct operational history from the entire repository.

## Map and durable context

- `crewai_agents/AGENTS.md`: runtime, editorial gates and per-role context.
- `scripts/AGENTS.md`: deployment, package publishing and verification helpers.
- `.github/workflows/deploy.yml`: verify → GitHub Packages → deployment. Explicit infrastructure-only/import-state operations skip publishing.
- `docs/agent-context.md`: work ownership and how to update persistent context.
- `docs/package-publishing.md`: package destinations, prerequisites and release versions.
- `docs/operational-recovery.md`: recovery limits, alerts and operator endpoints.
- `docs/incident-*.md`: dated evidence, not current service status. Recheck live status when needed.

## Local skills

Repository skills live under `.agents/skills/`. Select only the relevant skill:

- `package-publishing`: container/npm/Maven/Gradle publishing and registry verification.
- `railway-deployment`: environment scope, mounted state and deployment verification.
- `campaign-recovery`: diagnose failed/blocked runs and choose safe recovery.
- `editorial-workflows`: source grounding, role dependencies and reviewer gates.
- `agent-observability`: traces, model routing, usage and incident evidence.

## Working conventions

Read `git status --short` before editing: uncommitted application fixes may belong to earlier work. Preserve them. Runtime secrets belong in ignored `.env` files or provider secrets, never context/skill files. Print credential presence or sanitized errors, not environment values or API responses containing secrets.

Use `.venv/bin/python scripts/verify_marketing.py` for the offline suite. Node must be installed for executable n8n checks. CI installs dependencies from `crewai_agents/requirements.txt`. Docker/package publication and live integrations require separate verification; passing unit tests is not evidence of deployment or delivery.

When handing off, record changed behavior, tests, deployed revision (if any), verified outcomes and remaining external blockers. Update the relevant maintained document; never record secrets or assume dated incident details remain current. These files preserve repository context, not model conversation state.
