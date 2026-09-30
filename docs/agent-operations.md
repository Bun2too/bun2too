# Marketing team: work, observability and Atlassian records

For scheduled Facebook publishing and the daily retrospective loop, use the [MVP architecture](marketing-mvp-architecture.md) and [operations runbook](marketing-operations.md). This document describes the retained manual-campaign and Atlassian integration; daily scheduled campaigns do not automatically create Jira/Confluence work.

The application now records what each role was asked to do, its output and structured decisions, and the status of publication to Jira/Confluence. It uses nine roles:

| Role | Actual current work |
| --- | --- |
| PO | Campaign charter and actionable stories with stable work keys and acceptance criteria |
| BA | Audience hypotheses, requirements, KPIs, attribution and requirements gaps |
| Researcher | Evidence analysis from supplied material and referenced records; no live web research |
| Creative | Concepts, layouts, storyboards and image-generation briefs; no rendered image files |
| Writer | Campaign/social copy and calls to action |
| Engineering | Implementation specifications, tracking design and execution tasks; no code execution |
| Tester | Test cases and evidence gaps; does not claim unexecuted tests passed |
| Editor | Factual/brand review and release blockers |
| Delivery | Consolidated deliverables, proposed schedule and campaign package |

The run remains sequential: later roles receive earlier outputs. Publishing is deterministic application code after successful generation, rather than an agent holding credentials and inventing arbitrary API calls. Atlassian records are proposals and references, not proof that engineering or publishing has executed.

## Datadog setup

Configure Datadog through the [complete GitHub configuration checklist](deployment.md#complete-github-configuration-for-the-mvp), also in [README.md](../README.md#complete-github-configuration-for-the-mvp). It includes the CrewAI runtime JSON and the separate CI log credentials. This section explains the telemetry after configuration; it does not provide another settings snippet.

The container now runs `python start.py`. This loads local dotenv settings before starting `ddtrace-run python -m uvicorn ...`; running locally works with `.venv/bin/python crewai_agents/start.py`. Directly starting Uvicorn bypasses this bootstrap, so use the launcher for Datadog instrumentation.

`ddtrace==4.15.1` automatically instruments CrewAI crew/task/agent/tool activity and supported model calls. Custom workflow and Atlassian action spans carry the run ID as session ID and a `run_id` tag. Datadog exposes prompt/response details, model activity, latency and supported token/cost metrics. Costs are estimates and coverage depends on the provider integration. No Datadog Agent is assumed on Railway; `DD_TRACE_ENABLED=false` disables conventional APM export, while agentless LLM Observability exports directly to Datadog.

Open Datadog Agent/LLM Observability, select `bun2too-marketing-crew-team`, filter by environment and find the run/session ID. This traces SDK operations and configured tools, not every operating-system command. The agents currently have no shell/code-execution tools. Task prompts and concise decision summaries are review evidence; they are not guaranteed access to private internal model reasoning.

The span processor and local audit exporter redact configured secret values and credential-named fields. Avoid placing credentials or unnecessary personal data in briefs. Prompt/output capture intentionally exports campaign content to Datadog; redaction is defensive, not a comprehensive data-classification system.

Reference: [Datadog CrewAI integration](https://docs.datadoghq.com/llm_observability/guide/crewai_guide/).

## Atlassian destinations and credentials

Configured defaults:

- Jira: `https://bun2too.atlassian.net`, project `CMA` ([board 7](https://bun2too.atlassian.net/jira/software/projects/CMA/boards/7)).
- Confluence Cloud: space key `CMA`, user-facing links at `https://wiki.doc.bun2too.com`.

Use a dedicated Atlassian bot/service account with access to CMA. Add `ATLASSIAN_EMAIL` and `ATLASSIAN_API_TOKEN` as Railway runtime secrets. This adapter uses Cloud Basic authentication with email and an API token supported on the site-specific REST endpoints. Scoped tokens that require `api.atlassian.com/ex/...` need a gateway adapter; do not substitute them without changing the authentication/base URL configuration.

The Confluence API origin defaults to `https://bun2too.atlassian.net`, separate from the custom web domain. Confirm this is the underlying Confluence Cloud tenant; override `CONFLUENCE_BASE_URL` with its API-compatible HTTPS origin if different. Redirects are not followed with credentials. `CONFLUENCE_SPACE_KEY=CMA` is resolved to a numeric ID through Cloud API v2, or set `CONFLUENCE_SPACE_ID` explicitly. Optionally set `CONFLUENCE_PARENT_ID` to a “Marketing campaigns” parent page.

Set `ATLASSIAN_AUTO_PUBLISH=true` (the code default) to enable automatic publication after a complete campaign. Jira must support the `Epic`, `Story` and `Task` issue types and allow parent relationships under Epics. If the Epic creation screen requires an Epic Name custom field, set `JIRA_EPIC_NAME_FIELD` to its field ID. Other custom mandatory fields need project configuration or an adapter extension; failed creates stay visible rather than being silently discarded.

Call authenticated `GET /integrations/atlassian/check` from `/docs` to verify readable Jira issue types and resolve the Confluence space. It makes no writes. Actual create/update responses verify write permissions. The integration runs as the bot account; role ownership is recorded in labels/content, not as nine fabricated Atlassian user accounts.

References: [Jira issue API and parent relationships](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/), [Confluence Cloud pages API](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/).

## Organized automatic publishing

Always provide a stable `campaign_key`, for example `autumn-awareness-2026`:

```json
{
  "campaign_key": "autumn-awareness-2026",
  "brief": "Plan the bun2too autumn awareness campaign. Create a small prioritized backlog; no paid spend is approved.",
  "channels": ["facebook"],
  "brand_guidelines": "Clear, factual and useful. Flag unsupported claims.",
  "source_material": "Insert verified business/product information here.",
  "jira_issue_keys": [],
  "confluence_page_ids": [],
  "lesson_run_ids": []
}
```

Submit to `POST /campaigns`. After generation succeeds, the publisher creates/updates:

1. **One campaign Epic** in CMA.
2. **One campaign dossier** in Confluence CMA, organized by role, with decisions, evidence, assumptions, risks, proposed work and final deliverables. It links to the Epic.
3. **PO Stories and concrete execution Tasks** under the Epic, with acceptance criteria, dependencies, responsible role and references. Stories/tasks link to the dossier. No placeholder ticket is created simply because a role answered.

Repeat the same `campaign_key` for revisions. Stable `work_key` values identify stories/tasks; the model receives the existing keys and titles to reuse them. Existing Jira records are reread for current descriptions/statuses before a subsequent run. You can also explicitly supply additional Jira keys and Confluence page IDs; reads are restricted to the configured project/space. Referenced content remains untrusted input, not instructions to override agent rules.

The campaign dossier is updated through Confluence versions. Local run history retains the earlier prompts and outputs. Repeated unchanged backlog items do not create new issues. Titles are also compared to reduce duplicates when a model changes a work key. Removed proposals are not automatically deleted/closed; backlog triage should decide their disposition.

### Spam and edit controls

- `ATLASSIAN_MAX_WORK_ITEMS=12`: hard cap on Stories/Tasks per campaign, including earlier revisions. Maximum configurable value is 30. Extra proposals remain in the dossier and are marked deferred in the local event log.
- `ATLASSIAN_MAX_NEW_CAMPAIGNS_PER_DAY=3`: per-service-instance/SQLite-store limit on new campaign publication groups per UTC day. Maximum configurable value is 20. Production and QA have separate stores. This is not an organization-wide quota.
- One active generation per campaign key per instance/store. Fresh keys represent new campaigns, so do not generate a random campaign key for every retry.
- Remote markers are searched before creating records, and each local request is claimed atomically. These reduce duplicates; they do not provide a distributed exactly-once guarantee. Keep a single instance with persistent storage.
- Human-owned Jira status, assignee, sprint and priority are left untouched on updates. Existing human edits to generated summary/description, or a changed Confluence version, cause a `conflict` rather than an overwrite.
- Jira Stories/Tasks remain backlog proposals. No sprint is started, item transitioned, or employee assigned automatically. Board visibility depends on CMA board 7's filter.
- Requests without `campaign_key` remain local drafts. They do not automatically create Atlassian content. An explicit publish request can publish such a one-off run, subject to the same limits.
- Social-media publication is still controlled separately by the existing approval and n8n dispatch workflow. Automatic corporate documentation does not authorize social posting or ad spend.

## Inspect and recover work

All endpoints require the existing bearer `MARKETING_API_KEY`:

| Endpoint | Purpose |
| --- | --- |
| `GET /runs/{id}` | Run status, final artifact and completed structured task outputs |
| `GET /runs/{id}/work` | Prompt/task/action events plus campaign publication requests, status and remote links |
| `POST /runs/{id}/atlassian/publish` | Prepare/resume pending publications after configuration or a restart |
| `POST /publications/{id}/retry` | Retry a definite failure after correcting credentials/permissions/configuration |
| `POST /publications/{id}/reconcile` | Supply `{"remote_id":"CMA-123"}` or a page ID to verify/adopt a remote object after an ambiguous write |
| `POST /runs/{id}/lessons` | Record a reviewed lesson and its evidence for future runs |

An export failure does not discard a successful marketing artifact. Check `atlassian_sync_failed`, deferred-item events and publication statuses. `failed` means a retryable read failure or definite write rejection. `unknown` means a write may already have succeeded. `sending` after a process crash is also ambiguous: inspect the remote marker before acting. The reconciliation endpoint verifies destination, marker and content before adopting an object. It will not blindly declare a different revision published.

A `conflict` requires an operator to review the proposed local content against the human-edited remote record; there is no force-overwrite endpoint. An operator may manually apply the intended revision and use reconciliation to confirm an exact content match. Do not create a new campaign simply to bypass an unresolved conflict.

Publication retries/resumption are explicit API actions; there is no independent scheduled queue worker. A process crash during generation still requires inspection/resubmission. This is an operational foundation, not an unattended, self-healing department.

## Evidence-based learning

After reviewing results, record a lesson:

```json
{
  "lesson": "Lead with the customer benefit before implementation details.",
  "evidence": "Link to the reviewed campaign results and explain what the comparison showed.",
  "reviewed_by": "Your name"
}
```

Send it to `POST /runs/{completed-run-id}/lessons`. Include that run ID in a future request's `lesson_run_ids`. The selected lessons and their provenance are added to the crew's context. Reviewer names are supplied labels under the shared API key, not independently verified identities.

This is persistent, explicitly selected experience reuse. It does not train model weights, fetch campaign metrics automatically, grant new tools, or run forever without supervision. Reliable ongoing operation still needs measured campaign outcomes, a durable job scheduler/worker, individual identities, sprint policies and tested execution integrations.

## Persistence and rollout

Use a persistent `/data` volume and `DATA_DIR=/data` in both Railway environments. Production Terraform now declares the CrewAI history volume and sets `DATA_DIR`; attach a separate QA `/data` volume as part of QA setup. Back up the SQLite database. Losing it loses history, local quotas, conflict baselines and publication reconciliation information. Remote marker searches help recovery but are not a substitute for durable state.

If production and QA use the same CMA project/space for testing, use visibly distinct campaign keys such as `qa-autumn-awareness-2026`. Prefer a separate test project/space before testing automatic writes against corporate records; do not reuse a production campaign key from a separate QA store.

Local verification:

```sh
.venv/bin/python -m unittest discover -s crewai_agents/tests -v
```

Tests use mocked LLM/Atlassian responses and capture Datadog spans without exporting them. Live Datadog ingestion, Atlassian permissions, space resolution and your Jira custom fields must be checked after runtime credentials are configured.
