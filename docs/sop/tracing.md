# Tracing: agents, environments and credentials

Every Bun2too agent that runs (the products and the coding agents that build them) sends its traces to LangSmith (<https://api.smith.langchain.com>, US). This page is the single matrix of which runtime sends what, where, and with which credential. Status as of 2026-11-24; proposed by Claude and pending Codex's agreement on the crew-team rows.

## How a trace is addressed

LangSmith files a trace under an **agent** and one of its **environments**:

- **Agent ID** (`LANGSMITH_AGENT_ID`): one stable ID per application, never one per tier or per script. Use the ID, not the display name.
- **Environment** (`LANGSMITH_AGENT_ENVIRONMENT`): `local` on a developer's or agent's machine, `development`, `staging` for qa, `production` for prod.
- **Endpoint** (`LANGSMITH_ENDPOINT`): `https://api.smith.langchain.com` everywhere.
- **Workspace** (`LANGSMITH_WORKSPACE_ID`): only needed when a key reaches more than one workspace.
- **Key** (`LANGSMITH_API_KEY`, or the plugin's own name): a secret, one per runtime that is deployed.

Never set `LANGSMITH_PROJECT` or `LANGCHAIN_PROJECT` next to agent addressing; LangSmith rejects the combination with 400.

## The matrix

### Products

| Runtime         | Agent ID                | Environment  | Non-secret settings live in                                                                  | Key lives in                                                        | Owner  |
| --------------- | ----------------------- | ------------ | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------ |
| Relay qa        | `bun2too-support-agent` | `staging`    | GitHub environment `support-qa` variables `LANGSMITH_*` → Terraform → Railway agents service | `support-qa` secret `SUPPORT_RUNTIME_SECRETS` → `LANGSMITH_API_KEY` | Claude |
| Relay prod      | `bun2too-support-agent` | `production` | `support-prod` variables (not set until the owner decides)                                   | `support-prod` `SUPPORT_RUNTIME_SECRETS`, its own key               | Claude |
| Relay local     | `bun2too-support-agent` | `local`      | `bun2too-support-agent/.env.local` (git-ignored)                                             | The developer's own key, same file                                  | Claude |
| Crew-team qa    | `crew-ai-agents`        | `staging`    | Decided by Codex in the crew-team pipeline                                                   | One crew-team key per environment                                   | Codex  |
| Crew-team prod  | `crew-ai-agents`        | `production` | Same                                                                                         | Its own key                                                         | Codex  |
| Crew-team local | `crew-ai-agents`        | `local`      | The product's git-ignored env file                                                           | The developer's own key                                             | Codex  |

Relay's details, including payload hiding, are in its [ADR 0009](../../bun2too-support-agent/docs/adr/0009-langsmith-tracing.md) and [runtime secrets](../../bun2too-support-agent/docs/runtime-secrets.md#langsmith_api_key-langsmith-tracing).

### Coding agents

| Agent       | Plugin                                            | Config file (agent ID, key)                                                                                 | Environment                        |
| ----------- | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| Claude Code | `langsmith-tracing@langsmith-claude-code-plugins` | `~/.claude/langsmith.json`, or `TRACE_TO_LANGSMITH` and `CC_LANGSMITH_API_KEY` in `~/.claude/settings.json` | Fixed by the plugin (`production`) |
| Codex       | `tracing@langsmith-codex-plugins`                 | `~/.codex/langsmith.json`                                                                                   | Fixed by the plugin (`production`) |
| Antigravity | None documented by LangSmith yet                  | n/a                                                                                                         | n/a                                |

The owner holds the coding agents' keys and agent IDs.

## Rules

1. **One key per deployed runtime.** A key leaked or rotated affects one environment of one product. Never share a product's key with a coding agent, or the other way round.
2. **Never put an agent ID or key in a global environment.** That means shell profiles and the `env` block of `~/.claude/settings.json` or Codex's config. Every process an agent starts inherits them: a local Relay or crew-team run would send its traces to the coding agent's agent, or the reverse. Coding agents keep their agent ID and key in their plugin's config file; products read theirs from their own runtime settings.
3. **All or nothing.** A runtime sets the key, the agent ID and the environment together. Relay refuses to start with only some of them; other products should do the same. Agent addressing excludes any project setting, including the legacy `LANGSMITH_SESSION` and `LANGCHAIN_SESSION`.
4. **Customer text stays out of traces by default.** Products hide run inputs and outputs by default (`LANGSMITH_HIDE_INPUTS`, `LANGSMITH_HIDE_OUTPUTS`). A product shows them in an environment only after an ADR and the owner say so. Error spans carry the exception's class, never its message.
5. **Prove it lands.** After setting tracing up, run one real request and find its trace in LangSmith by ID before calling it done.
