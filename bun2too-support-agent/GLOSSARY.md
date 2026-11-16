# Glossary

The shared language for Relay. Code, tickets, prompts and docs use these terms. When you reach for a word under _Avoid_, use the canonical term. Update this file inline when a grilling session sharpens a term (`/domain-modeling`).

## Product

**Relay**: the platform. White-label; never shown to end customers unless a tenant chooses to.

**Tenant**: one brand running on Relay, configured by one file in `tenants/`. `bun2too` is the demo tenant.
_Avoid_: client, customer (ambiguous with the tenant's own customers), org, account

**Customer**: the person asking a tenant for help.
_Avoid_: user (reserved for operators of Relay), visitor, requester

**Operator**: a tenant's human support staff working escalated cases in Jira or ServiceNow.
_Avoid_: agent (reserved for AI agents), rep, human agent

**Channel**: where an intake comes from: `web_widget`, `a2a`, `email`, `marketplace`, `retail`.
_Avoid_: source, surface, integration

## Work

**Intake**: one inbound request to Relay, before it becomes a case. Validated against `IntakeRequest`.
_Avoid_: ticket (reserved for Jira/ServiceNow records), request, submission

**Case**: Relay's own record of one customer problem, from intake to resolution. Owns status and history.
_Avoid_: ticket, issue, incident, conversation

**Case event**: one append-only row recording a case transition or finding. Status is derived from case events.
_Avoid_: log, history entry, audit row

**Ticket**: a record in an external system of record: a Jira issue or a ServiceNow incident/case. A case has at most one ticket per system.
_Avoid_: using "ticket" for the case

**Correlation key**: `relay-{tenant}-{caseId}`. Stored on every ticket so retries find instead of create.

**Classification**: the orchestrator's structured read of an intake: intent, severity, sentiment, product area, language.

**Intent**: which specialist should own the case: `knowledge`, `identity`, `integration`, `commerce`, `privacy`, `other`.

## Agents

**Orchestrator**: the LangGraph supervisor graph that owns routing and case state. Never answers the customer itself.
_Avoid_: router, dispatcher, main agent, supervisor agent

**Specialist**: a narrow LangChain agent with its own prompt, tool allow-list and eval set, e.g. `knowledge_agent`.
_Avoid_: sub-agent (reserved for coding subagents in the factory), worker, skill

**Assessment**: the orchestrator node that decides between resolve, await customer, and escalate, using policy in code.

**Auto-resolution**: a case closed by a specialist's answer or action without an operator.

**Escalation**: handing a case to operators, with a handoff summary on both tickets.
_Avoid_: handoff (as a noun for the whole step), transfer

**Policy**: tenant-configured rules in `relay_agents.policy` that gate auto-resolution and write actions.

**Guardrail trip**: a policy refusal caused by safety signals: injection detected, PII in output, tool error budget exceeded.

## Factory

These follow Matt Pocock's software-factory vocabulary.

**Task**: a kind of work the factory performs: explore, implement, review, rework, ratchet, retro.

**Trigger**: the event that starts a run: a label, a PR event, a clock.

**Run**: one execution of a task on one runner. Never waits for a human.
_Avoid_: session, job

**Brake**: automated checks, automated review, human review. Every trigger needs all three.
