@AGENTS.md

## Claude Code specifics

- Open Claude Code at the monorepo root (`..`). The root `CLAUDE.md`, shared agents, hooks and plugins load from there, and this product's skills load as `bun2too-support-agent:<skill>`.
- Run product commands with `pnpm -C bun2too-support-agent <script>` from the root, or from this folder.
