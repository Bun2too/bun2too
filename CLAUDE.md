@AGENTS.md

## Claude Code specifics

- Open Claude Code at this root. Shared agents, skills, hooks and plugins load from `.claude/` here. Product skills under `<product>/.claude/skills/` load as directory-scoped skills, for example `bun2too-support-agent:verify-relay`.
- Plugins are enabled in `.claude/settings.json`. Accept the marketplace prompts on first run:
  - `agent-skills@addy-agent-skills` is primary. Use `/spec`, `/plan`, `/build`, `/test`, `/agent-skills:review`, `/code-simplify` and `/ship`.
  - `mattpocock-skills@claude-plugins-official` provides `/grill-with-docs`, `/to-tickets` and `/pr`.
- Start every subagent with a fresh context. Personas do not invoke other personas; orchestration lives in skills and workflows.
- Hooks block edits to secrets, lockfiles and generated files, and format files in products whose dependencies are installed. Do not disable them to get past an error; fix the cause.
