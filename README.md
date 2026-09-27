# Bun2too marketing agents

A self-hosted CrewAI marketing team with n8n scheduling, a persistent campaign journal, Facebook article/post publishing and Datadog observability. Nine roles run inside one Railway FastAPI service: Product Owner, Business Analyst, Researcher, Creative, Writer, Engineering, Tester, Editor and Delivery Manager.

Start with the [complete architecture and agent specifications](docs/marketing-mvp-architecture.md), including the end-to-end diagram, role contracts, release policy, persistence, retrospective loop and deployment boundaries. The [operating runbook](docs/marketing-operations.md) contains configuration, local checks, live activation and troubleshooting. An editable diagram is in [marketing-architecture.mmd](docs/marketing-architecture.mmd).

## Current deployment and implementation status

The n8n UI is [n8n.bun2too.com](https://n8n.bun2too.com/). Railway also has [crewai.bun2too.com](https://crewai.bun2too.com/) configured; its `/health` responded successfully during inspection. The deployed CrewAI app currently lacks the new `/ready` endpoint and the inspected production runtime lacks model, marketing authentication, Facebook and Datadog configuration. A running container is not yet an operating marketing team.

This working tree adds the daily workflow, durable scheduled jobs, publication/feedback operations, log export and CI installation. Live activation still requires approved business facts/audience, Page credentials, n8n management/HTTP credentials and preservation of the existing n8n data. No Facebook post or live workflow activation is implied by passing the local tests.

## Daily marketing operation

The owner-selected policy is one daily article and one Facebook post linking to it, automatically released within business rules to [Bun2too's Page](https://www.facebook.com/bun2too). A stable pseudorandom target is selected between **08:00 and 22:30 America/Chicago**, respecting daylight saving time. n8n polls every five minutes; generation begins after 08:00 and engagement is collected at 07:45 for the next retrospective.

1. The application gathers approved facts/source snapshots and previous measured outcomes.
2. All nine roles produce structured, saved deliverables and an article/post package.
3. Tester/Editor decisions and deterministic business-rule checks gate automatic approval.
4. A deterministic publisher sends only approved content, with an atomic claim and daily quota.
5. Facebook post IDs and available engagement counts feed the next campaign's analysis and hypothesis.

Model agents never receive platform credentials or control destinations. Creative/Engineering produce briefs and specifications; they do not render images, execute arbitrary code or spend money. Incomplete evidence holds content for review. Ambiguous publishing responses are never automatically resent.

## Configure and run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r crewai_agents/requirements.txt
cp crewai_agents/.env.example crewai_agents/.env
```

If `.env` already exists, edit it instead of overwriting it. Set `MARKETING_API_KEY`, `LLM_MODEL` and the corresponding model-provider key. Fill the business profile at `crewai_agents/config/marketing.json`; placeholders fail validation. Keep publishing disabled for initial local generation checks.

```sh
.venv/bin/python crewai_agents/start.py
```

Open `http://localhost:8000/docs`, select **Authorize** and enter the marketing API key. `/campaigns` creates a manual draft; `/runs/{id}` and `/runs/{id}/work` expose artifacts and the audit trail. `/automation/tick` creates a durable scheduled job when enabled; `/automation/status` shows publication outcomes. Public article pages are exposed only once an approved publication is attempted.

All roles execute within this service using the configured LLM provider. No CrewAI cloud deployment/account is required. Railway Variables must be configured separately from the local `.env`, or managed through the new Terraform runtime-variable maps.

## Verify before committing

```sh
.venv/bin/python scripts/verify_marketing.py --terraform
```

Requires installed dependencies and initialized Terraform providers. Tests use mocked external services, exercise a complete scheduled cycle and check concurrency, restart handling, publication safety and log export. Terraform tests use a mock provider and do not apply infrastructure. Real model, n8n, Facebook and Datadog acceptance checks are listed in the [runbook](docs/marketing-operations.md).

## Deploy applications and workflows as code

The [GitHub workflow](.github/workflows/deploy.yml) tests code, checks HCP/Railway targets, applies Terraform, uploads CrewAI, checks runtime readiness and installs/activates the version-controlled [n8n workflows](n8n/marketing-operations.json). Normal `deploy` requires workflow credentials and `N8N_ACTIVATE_WORKFLOWS=true`; missing configuration fails instead of silently skipping the application. The manual `infrastructure-only` operation applies Terraform without uploading CrewAI or installing workflows. Import-state mode only imports and plans. Workflow IDs, links and verified active states appear in the GitHub summary.

| Branch | GitHub/Railway environment | HCP workspace |
| --- | --- | --- |
| `main` | production | Environment's `TF_WORKSPACE`; currently `code-monkey-army` |
| `qa` | qa | Separate configured `TF_WORKSPACE` |

Production owns shared project/service definitions. Runtime variables target the selected environment. QA needs separate volumes and test credentials; do not point QA publishing at the production Page. CrewAI stores scheduled jobs, articles, approvals and events in `/data/runs.sqlite3` on its persistent volume, with a single worker/replica.

n8n requires persistent `/home/node/.n8n`. The optional Terraform volume must be enabled only after preserving/restoring the existing configured instance's database and encryption key. Adding an empty mount does not migrate its data. See the [migration procedure](docs/marketing-mvp-architecture.md#n8n-persistence-and-existing-instance-migration) and [infrastructure deployment guide](docs/deployment.md).

## Observability and existing integrations

Set CrewAI `DD_LOGS_ENABLED=true`, `DD_API_KEY` and the correct `DD_SITE` to export operational events from its durable journal. `DD_LLMOBS_ENABLED=1` enables agent/task/model traces through the `start.py` launcher. GitHub's separate Datadog secret enables deployment-outcome logs. The n8n workflows record success/failure execution events. Datadog queries and live verification are in the runbook; no host metrics or monitor provisioning is implied.

Existing manual campaign Jira/Confluence publishing, reviewed lessons and legacy n8n webhook dispatch remain available. See [agent operations](docs/agent-operations.md). The daily automated campaign uses the new deterministic publisher and does not create corporate tickets every day. Do not also route the same scheduled content through the legacy publishing webhook.
