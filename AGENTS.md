# Bun2too: shared agent spec

Bun2too is the business. This directory is its monorepo: shared rules, agents, skills and SOPs at the root, and one folder per product. Products are git subtrees, so each one can still be split out and pushed to its own GitHub repo (see [docs/sop/subtrees.md](docs/sop/subtrees.md)).

Every agent, whatever tool runs it, reads this file first and then the `AGENTS.md` nearest to the files it touches. Where they disagree, the nearer file wins for that product's code. The rules in [Always](#always) apply everywhere.

## Map

| Path                     | Product                                                     | Stack                                   | Deploys to                                | Its own spec                                                         |
| ------------------------ | ----------------------------------------------------------- | --------------------------------------- | ----------------------------------------- | -------------------------------------------------------------------- |
| `bun2too-support-agent/` | **Relay**: multi-agent support intake (REST + A2A)          | TypeScript (Hono) + Python (LangGraph)  | Railway POC: dev, qa, prod. GCP for GA    | [AGENTS.md](bun2too-support-agent/AGENTS.md)                         |
| `bun2too-crew-team/`             | Marketing crew: CrewAI agents, publishing, n8n schedules    | Python (FastAPI, CrewAI), n8n           | Railway (its own pipeline, mirror repo)   | [AGENTS.md](bun2too-crew-team/AGENTS.md)                                     |
| `bun2too-website/`       | bun2too.com                                                 | Next.js on Netlify                      | Netlify (its own pipeline, mirror repo)   | [AGENTS.md](bun2too-website/AGENTS.md)                               |
| `.claude/`               | Shared agents, skills, hooks and plugin settings            |                                         |                                           |                                                                      |
| `.github/`               | Monorepo CI/CD and the agent factory workflows              |                                         |                                           | [docs/factory.md](docs/factory.md)                                   |
| `docs/`                  | SDLC, factory roles, SOPs, organisation-wide ADRs           |                                         |                                           | [docs/sdlc.md](docs/sdlc.md)                                         |

## How work moves (summary of [docs/sdlc.md](docs/sdlc.md))

We follow Addy Osmani's [agent-skills](https://github.com/addyosmani/agent-skills) lifecycle. Matt Pocock's [skills](https://github.com/mattpocock/skills) fill two gaps: the GitHub Issues bridge and domain grilling.

| Phase      | Run                                        | Exit evidence                                                                 |
| ---------- | ------------------------------------------ | ----------------------------------------------------------------------------- |
| **Define** | `/spec` (with `/grill-with-docs` when terms or ADRs change) | `SPEC.md` or a `spec` issue a human approved                 |
| **Plan**   | `/plan`, then `/to-tickets`                 | Small tasks as GitHub issues with acceptance criteria and `Blocked by` edges |
| **Build**  | `/build` (test-first, one slice at a time)  | Each slice green and committed                                                |
| **Verify** | `/test` plus the product's verify skill     | Commands, outputs and trace IDs from the running system                       |
| **Review** | `factory-review` skill (`/agent-skills:review` locally) | One comment ending `VERDICT: PASS` or `VERDICT: FAIL`             |
| **Ship**   | `/ship` via the CI/CD pipeline              | dev → qa → prod deploy records and a rollback path                            |

In Claude Code, `/review` is a built-in command; use `/agent-skills:review` for Addy's review.

## Always

1. **Trunk-based.** `main` is the trunk. Branches live less than a day, and unfinished work hides behind a flag or config. No long-lived `dev` or `qa` branches. Environments are deploy targets, not branches. See [docs/sop/trunk-based-development.md](docs/sop/trunk-based-development.md).
2. **One product per commit.** A commit touches one subtree prefix, or only root files. This keeps `git subtree split` clean.
3. **Spec before code.** Anything larger than a one-line fix starts from an approved spec or issue. Agents do not invent scope.
4. **Prove it works.** Passing unit tests is not evidence of behaviour. Each product's verify skill drives the real system. If a check could not run, say **inconclusive** and why.
5. **Smallest change that solves it.** Delete before you add. No speculative flags, parameters or abstractions.
6. **Respect existing work.** Run `git status --short` before editing. Never reset, discard, stage or commit someone else's uncommitted changes to make your own change fit.
7. **Secrets stay out.** Never read, print, commit or paste `.env*`, tokens or provider responses that contain secrets. Runtime secrets live in GitHub environment secrets and HCP Terraform, never in code, docs, skills or agent context.
8. **Hard-to-reverse decisions get an ADR**: organisation-wide in `docs/adr/`, product-specific in the product's `docs/adr/`.
9. **Agents never push to `main`, force-push, or change CI permissions.** Only the factory's review loop merges, and only a product PR whose CI and review both passed on the exact commit it merges. People merge factory PRs (rule 10). Deploys to prod need a human approval in the `support-prod` GitHub environment.
10. **The factory changes only with human review.** Changes under `.claude/`, `.cursor/`, `.github/`, any `AGENTS.md` or `CLAUDE.md`, `docs/factory.md` and `docs/sdlc.md` are never auto-merged.
11. **An agent that runs code cannot send secrets out.** A factory job that gives an agent a shell runs those commands with no network and no credentials in their environment, without `sudo`, behind an outbound allowlist. Its output is secret-scanned before anything is pushed. A role or provider that cannot meet this stays off. See [docs/factory.md](docs/factory.md#spend-and-safety).

## Shared agents and skills

These ship from the root and serve every product.

| Kind     | Name                                                             | Use                                                                                            |
| -------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Plugin   | `agent-skills` (Addy Osmani)                                     | Lifecycle commands and skills; personas `code-reviewer`, `test-engineer`, `security-auditor`, `web-performance-auditor` |
| Plugin   | `mattpocock-skills`                                              | `/grill-with-docs`, `/to-tickets`, `/pr`, triage vocabulary                                    |
| Agent    | [spec-reviewer](.claude/agents/spec-reviewer.md)                 | Checks a diff against its spec. Fresh context, read-only                                      |
| Agent    | [verifier](.claude/agents/verifier.md)                           | Runs the touched product's verify skill and returns evidence                                  |
| Skill    | [factory-review](.claude/skills/factory-review/SKILL.md)         | Three fresh-context reviewers, one comment, a machine-readable verdict                        |
| Skill    | [railway-deploy](.claude/skills/railway-deploy/SKILL.md)         | Plan, deploy, verify and roll back a Railway service safely                                   |
| Skill    | [subtree-sync](.claude/skills/subtree-sync/SKILL.md)             | Pull from or push to a product's mirror repo                                                  |
| Spec     | [docs/factory.md](docs/factory.md)                               | The roles automated runs play (Explore, Implement, Review, Rework, Hygiene, Ratchet, Retro)   |

Product skills live with the product and are listed in its `AGENTS.md`. Examples: `bun2too-support-agent/.claude/skills/verify-relay`, `bun2too-crew-team/.agents/skills/*` and `bun2too-website/.agents/skills/*`.

## SOPs

- [Trunk-based development](docs/sop/trunk-based-development.md)
- [Environments and release](docs/sop/environments-and-release.md): dev, qa and prod, promotion and rollback
- [Subtrees](docs/sop/subtrees.md): mirrors, pull and push, and conflict handling
- [Issue tracker](docs/agents/issue-tracker.md), [triage labels](docs/agents/triage-labels.md), [domain docs](docs/agents/domain.md)

## Agent skills (Matt Pocock skill configuration)

- **Issue tracker:** GitHub Issues on the monorepo via `gh`. See `docs/agents/issue-tracker.md`.
- **Triage labels:** the five canonical labels plus `area:*`. See `docs/agents/triage-labels.md`.
- **Domain docs:** multi-context; each product keeps its own `GLOSSARY.md` and `docs/adr/`. See `docs/agents/domain.md`.
