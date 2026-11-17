# Bun2too

The Bun2too monorepo: shared agent specs, skills and SOPs at the root, one subtree per product.

| Product                                              | What                                         |
| ---------------------------------------------------- | -------------------------------------------- |
| [bun2too-support-agent](bun2too-support-agent/)      | Relay: multi-agent support intake            |
| [bun2too-crew-team](bun2too-crew-team/)                              | Marketing crew (CrewAI, n8n)                 |
| [bun2too-website](bun2too-website/)                  | bun2too.com (Next.js on Netlify)             |

Start here: [AGENTS.md](AGENTS.md) → [docs/sdlc.md](docs/sdlc.md) → the product's `AGENTS.md`.

Published for the team:

- Relay architecture: <https://claude.ai/artifact/Hje8YdHV3njx2TXgywGS1D>
- Relay three-week execution plan: <https://claude.ai/artifact/HxXS4MGBucVm5BYuY2zMSM>
- Relay pitch deck: <https://claude.ai/artifact/Pz9GdCothnDgwBEFVqWmae>

## One-time setup (a person)

1. Create `Bun2too/bun2too` on GitHub, push this repo, and create the mirror `Bun2too/bun2too-support-agent`. Protect `main` as in [the trunk SOP](docs/sop/trunk-based-development.md) (required check: `ci`).
2. Secrets: `ANTHROPIC_API_KEY` and `FACTORY_TOKEN` at repo level. Then the GitHub environments listed in [environments and release](docs/sop/environments-and-release.md).
3. HCP Terraform workspaces: see [the Railway README](bun2too-support-agent/infra/terraform/railway/README.md).
4. Labels: [triage labels](docs/agents/triage-labels.md). Install the Claude GitHub app.
5. In Claude Code, open this folder and accept the plugin prompts (Addy's `agent-skills`, Matt Pocock's skills).
6. Clone to local disk for daily work. Git and `node_modules` inside a synced Google Drive folder are fragile ([ADR 0001](docs/adr/0001-monorepo-with-subtrees-and-shared-specs.md)).
