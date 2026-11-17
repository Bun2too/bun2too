# 0001. One monorepo with product subtrees and shared agent specs

- Status: accepted
- Date: 2026-11-16

## Context

Bun2too runs three products: the support agent (Relay), the marketing crew and the website. Each one had its own agent rules, skills and CI. The support agent alone defined seven single-purpose agent files. Agents working on one product could not see company-wide rules, and the same advice was copied between repos and drifted apart.

## Decision

- `bun2too/` is the monorepo and the business's root. It holds shared specs (`AGENTS.md`, `docs/sdlc.md`, `docs/factory.md`), shared agents and skills (`.claude/`), SOPs, organisation-wide ADRs, and all CI/CD.
- Products are **git subtrees**: `bun2too-support-agent/`, `bun2too-crew-team/`, `bun2too-website/`. Their GitHub repos become mirrors that receive `main` through `git subtree push`.
- Roles are specified once, in `docs/factory.md`, instead of one agent file per role. The root keeps only two custom agents (`spec-reviewer`, `verifier`); the other personas come from Addy Osmani's plugin.

## Consequences

- One clone gives an agent the whole context. A product's `AGENTS.md` keeps only what is specific to that product.
- Subtrees keep plain files, with no submodule pointers, so tools, Netlify and Railway need no special handling. In exchange, syncing a mirror is a deliberate step ([SOP](../sop/subtrees.md)).
- A product's mirror does not contain the root specs. Agents should work in the monorepo, not the mirror.
- The monorepo sits in Google Drive. Git in a synced folder can be corrupted if two machines edit at once, and `node_modules` and `.venv` would sync. Recommended: keep the clone on local disk and use GitHub as the shared copy.
