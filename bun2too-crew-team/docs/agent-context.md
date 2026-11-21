# Persistent agent context

Coding assistants discover repository instructions in root and scoped `AGENTS.md` files. The marketing team gets a separate context file per role from `crewai_agents/app/agent_context/`, loaded by `build_crew` into that role's backstory. Neither mechanism stores hidden model reasoning or restores an old conversation. Run-specific evidence remains in SQLite; code/configuration remains the authoritative behavior.

Read the [marketing glossary](../GLOSSARY.md) before naming domain concepts. In the monorepo, shared root rules and organization context also apply. Codex currently focuses on this product and the website; coordinate file ownership with the owner/Claude and preserve concurrent work. Handoffs name the approved issue/spec, paths, revision, checks and remaining external blockers.

The nested deployment workflow is a mirror release definition. Root CI runs offline checks; it does not activate n8n, publish packages or run paid candidate evaluations. Legacy environment branches are not the monorepo development model.

| Agent | Durable work knowledge | Output responsibility |
| --- | --- | --- |
| Product Owner | Topic choice and enterprise reader value | Scope and reasoned topic selection |
| Business Analyst | Audience, acceptance criteria, measurement limits | Requirements and measurable criteria |
| Researcher | Current-source grounding and evidence limits | Claim/source map and uncertainty |
| Creative | Editorial illustration and accessibility | Visual brief, not a rendered asset |
| Writer | Original copy and factual attribution | Article and Facebook draft |
| Engineering | Publisher contract and format | Concrete implementation/format findings |
| Editor | Corrections, novelty and brand accuracy | Final edited candidate and review |
| Tester | Independent final-copy verification | Evidence-backed approval or rejection |
| Delivery | Exact final assembly and unresolved findings | Structured MarketingArtifact |

Scheduled and manual task details differ; see `app/crews.py` and `app/agents.json`. Do not copy their full prompts into every context file. Change a role context when a stable working rule changes. Keep transient campaign results in run/task records and operational findings in dated incident reports. Record verification date and deployment revision for live claims.

Reusable maintenance procedures live in `.agents/skills/`, with focused `SKILL.md` entrypoints referencing existing scripts/runbooks. They are repository-local coding-agent skills; runtime CrewAI roles do not receive permission to execute those scripts or deploy infrastructure. A tool that does not automatically discover `.agents/skills` can follow the root `AGENTS.md` links and read the selected file explicitly.
