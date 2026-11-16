# 0002. Addy Osmani's agent-skills as the primary SDLC

- Status: accepted; supersedes the support agent's earlier use of pstack
- Date: 2026-11-16

## Context

Three open skill sets cover the agentic SDLC: Addy Osmani's agent-skills, Matt Pocock's skills and Lauren Tan's pstack. They overlap on clarifying the ask, specs, TDD, review and verification. Running all three gives agents competing instructions for the same step.

## Decision

- **Primary:** `agent-skills@addy-agent-skills`. Its six phases (Define, Plan, Build, Verify, Review, Ship), its commands and its personas are our lifecycle.
- **Complement:** `mattpocock-skills` only where Addy has no equivalent: `/to-tickets` (GitHub Issues with blocking edges), `/grill-with-docs` (updates the glossary and ADRs), `/pr` (PR body format) and triage vocabulary.
- **Retired:** the pstack plugin. Its two ideas Addy lacks, "encode lessons in structure" and "never block on the human", are written into `docs/factory.md` and each product's `enforcement.md`.
- The overlap table in `docs/sdlc.md` says which skill wins at each step.

## Consequences

- Agents get one lifecycle with explicit exit evidence at each phase.
- `/review` clashes with Claude Code's built-in command, so the docs say `/agent-skills:review`.
- Plugins update upstream. Read Addy's changelog when the lifecycle changes, and update `docs/sdlc.md` if commands change.
