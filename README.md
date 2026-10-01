# Bun2too marketing agents

A self-hosted CrewAI marketing team with n8n scheduling, a persistent campaign journal, Facebook article/post publishing and Datadog observability. Nine roles run inside one Railway FastAPI service: Product Owner, Business Analyst, Researcher, Creative, Writer, Engineering, Tester, Editor and Delivery Manager.

Configure GitHub using the [complete checklist below](#complete-github-configuration-for-the-mvp), also maintained at the top of [the deployment guide](docs/deployment.md#complete-github-configuration-for-the-mvp). The other documents explain operation and design; they are not additional configuration checklists.

For design details, see the [complete architecture and agent specifications](docs/marketing-mvp-architecture.md), including the end-to-end diagram, role contracts, release policy, persistence, retrospective loop and deployment boundaries. The [operating runbook](docs/marketing-operations.md) contains configuration, local checks, live activation and troubleshooting. An editable diagram is in [marketing-architecture.mmd](docs/marketing-architecture.mmd).

<!-- BEGIN GITHUB MVP CONFIGURATION: keep identical in README.md and docs/deployment.md -->
## Complete GitHub configuration for the MVP

Use this checklist for **scheduled article creation, automatic Facebook Page publication, engagement feedback, n8n persistence and Datadog logs/traces**. All GitHub settings consumed by the current deployment workflow are listed below. Runtime settings inside the two JSON secrets are listed separately. This configures the self-hosted Railway application, not a CrewAI cloud deployment or email delivery.

### 1. Where to enter the settings

Open **GitHub repository → Settings → Environments**. Create/select `production` and `qa`, then use **Environment variables** and **Environment secrets** as indicated below. Add values separately to each environment. Local `.env` files do not populate GitHub or Railway.

| Branch | GitHub environment | Railway environment | HCP workspace |
| --- | --- | --- | --- |
| `main` | `production` | Existing environment named `production` | Existing production state, currently `code-monkey-army` |
| `qa` | `qa` | Separate environment named `qa` | Separate workspace owning QA state |

Restrict production deployments to `main` and QA deployments to `qa` in GitHub's environment settings. The YAML does not configure those restrictions for you. QA needs its own API keys, URLs/credential IDs, database password, storage and authorized **test Facebook Page**. Full scheduled QA deployment also requires publishing enabled, against that test Page. For tests with publishing disabled use manual draft generation instead of the scheduled full-deploy path.

### 2. GitHub Environment variables — individual entries

“Required” means configure for the complete MVP even where a lower-level script permits an empty/default value. IDs below are the recorded production targets; verify they still identify your services. Do not copy production environment IDs, public URLs or Page credentials into QA.

| Variable name | Requirement | Production value / where to get it | Purpose |
| --- | --- | --- | --- |
| `TF_CLOUD_ORGANIZATION` | Required | `Bun2tooinc` — HCP organization **name**, not `org-…` ID | Select Terraform organization |
| `TF_WORKSPACE` | Required | `code-monkey-army`, if it still owns production state | Select existing HCP state; use a separate workspace for QA |
| `RAILWAY_PROJECT_ID` | Required | `f5a4899e-a958-4353-b6a3-99a57b80ebad` | Target Railway project |
| `RAILWAY_ENVIRONMENT_ID` | Required | `72e3af2d-37a3-430f-92ed-e0941b0b6435`; QA must differ | Target the correct Railway environment |
| `POSTGRES_SERVICE_ID` | Required | `dd68258c-7986-46e8-b8a7-e2830403ba17` | Configure/check Postgres |
| `CREWAI_SERVICE_ID` | Required | `8eefe858-998d-4887-9f5c-bcacc5a16e3a` | Upload application and set CrewAI runtime variables |
| `N8N_SERVICE_ID` | Required with the n8n runtime map below | `1120d946-3a88-41f7-9096-4135d5f70d94` | Target n8n runtime variables; also usable during import |
| `CREWAI_BASE_URL` | Required | `https://crewai.bun2too.com` | Public HTTPS API origin used by readiness checks and n8n; no `/docs` suffix |
| `N8N_BASE_URL` | Required | `https://n8n.bun2too.com` | n8n management API origin; no `/api/v1` suffix |
| `N8N_MARKETING_CREDENTIAL_ID` | Optional | Existing Header Auth credential ID to adopt; otherwise leave empty | CI provisions/reuses `Bun2too Marketing API (production)` or `(qa)` and writes the real ID into both workflows |
| `N8N_ACTIVATE_WORKFLOWS` | Required | `true` | Full deploy must activate the daily workflow |
| `N8N_VOLUME_READY` | Storage migration acknowledgement | Set `true` only after preparing backup/restore for an existing unpersisted instance or confirming it is empty | CI ensures `/home/node/.n8n` storage in the selected environment through the Railway API. This flag permits creation after migration preparation; it never detaches storage |
| `DD_SITE` | Default available; set explicitly for observability | `us5.datadoghq.com` if your Datadog account is in US5; otherwise its actual site | Datadog intake for **GitHub deployment logs**; default US5 |
| `POSTGRES_USER` | Optional override | Default `postgres`; preserve the initialized database's actual user | Postgres initialization configuration |
| `POSTGRES_DB` | Optional override | Default `bun2too`; preserve the initialized database's actual database | Postgres initialization configuration |
| `MARKETING_DEPLOY_ENABLED` | **Retired — remove it** | Not required. An existing `false` value rejects full deploy | No longer controls silent skipping; use explicit `infrastructure-only` when intended |

Service IDs can be shared across Railway environments in one project; environment IDs must differ. Merely changing `POSTGRES_USER`, `POSTGRES_DB` or the password does not migrate an initialized database.

### 3. GitHub Environment secrets — individual entries

Create these **eight entries** for the full MVP including Datadog and pipeline-managed runtime configuration. The two `*_RUNTIME_CONFIG` entries contain JSON objects, not file paths.

| Secret name | Exact contents | Used by |
| --- | --- | --- |
| `TF_API_TOKEN` | HCP team token or permitted user token with workspace read, state read/write and lock/unlock access | Terraform backend/preflight; HCP workspace must use **Local** execution mode |
| `RAILWAY_API_TOKEN` | Railway account/workspace API token with access to the project/environment | Railway API, Terraform provider and CLI upload; the workflow maps the provider alias itself |
| `POSTGRES_PASSWORD` | Correct password for this environment; different in QA | Postgres Terraform variable and configuration readback |
| `MARKETING_API_KEY` | A long random secret **you generate**; CI injects it into both the CrewAI runtime map and the encrypted n8n Header Auth credential | Deployed API authentication and post-deployment readiness check |
| `N8N_API_KEY` | Management API key created in the target n8n account, with access to list/read/create/update/activate the managed workflows | Install and verify n8n workflows; **not** used to authenticate CrewAI calls |
| `MARKETING_RUNTIME_CONFIG` | Complete CrewAI JSON object from step 4, with real values | Terraform writes these variables into the selected Railway CrewAI service |
| `N8N_RUNTIME_CONFIG` | Complete n8n JSON object from step 4, preserving the current encryption key | Terraform writes these variables into the selected Railway n8n service |
| `DD_API_KEY` | Datadog API key for the configured site | **GitHub deployment outcome logs**; also supply a runtime Datadog key inside the CrewAI JSON for agent activity |

The two Datadog keys may be the same valid key or separate keys for the same site. Configuring only standalone `DD_API_KEY` does not forward it to CrewAI. The pipeline can run without deployment-log ingestion, but that does not fulfill the requested Datadog observability.

### 4. Paste the complete runtime JSON secrets

For production, save `MARKETING_RUNTIME_CONFIG` under the repository's **Settings → Environments → production → Environment secrets**. A pipeline environment showing `TF_VAR_marketing_runtime_config` with only `MARKETING_API_KEY` means no additional runtime fields reached Terraform. Separate GitHub secrets named `LLM_MODEL` or `OPENAI_API_KEY` are not read by this workflow.

Full deployments validate the declared model, automation, worker and Facebook delivery settings locally before Terraform changes anything. This does not contact CrewAI, so it supports first deployment. It validates configuration shape, not provider credentials, model access, Facebook permissions or the business profile. Supply the chosen model provider's credentials in the map as well. Infrastructure-only and import operations do not require the scheduled-application configuration.

If `/ready` returns `model_configured: false` and `automation_enabled: "false"`, API authentication has succeeded but the runtime is missing `LLM_MODEL` and automation is disabled. `missing_configuration: []` is not an overall readiness verdict: the server's marketing checks only run when automation is enabled. Correct the secret and redeploy; retries cannot populate missing settings.

All JSON values below are **strings**, including booleans. Replace every `REPLACE_…` placeholder. GitHub does not expand expressions or substitute one secret inside another secret's JSON: paste the actual values. Keep the complete map when editing it; deleting an already-managed key can cause Terraform to delete that Railway variable. These sensitive values are stored in HCP state even though Terraform hides them in normal output.

CrewAI and n8n runtime maps use `railway_variable_collection`, which batches each map and requests one service redeployment per changed collection. The old per-key resources requested a redeployment for every key and could fail with `Service deployment rate limit exceeded`. Terraform 1.7+ `removed` blocks discard the old per-key state without deleting live variables; the new collections upsert the supplied values, including keys left by a partially failed apply. Keep both JSON maps complete during this migration: omitted legacy keys remain live but are not adopted by the collection. No manual state removal or key rotation is required. Deploy the commit containing the collection change after Railway's rate limit clears; rerunning the old revision repeats the per-key deployment requests. A separate Railway 503 can still require retrying after service recovery.

**Secret: `MARKETING_RUNTIME_CONFIG`** — example using an OpenAI-backed model:

```json
{
  "LLM_MODEL": "REPLACE_WITH_YOUR_PROVIDER_MODEL",
  "OPENAI_API_KEY": "REPLACE_WITH_YOUR_MODEL_PROVIDER_KEY",
  "PUBLIC_API_BASE_URL": "https://crewai.bun2too.com",
  "FACEBOOK_PAGE_ID": "REPLACE_WITH_BUN2TOO_NUMERIC_PAGE_ID",
  "FACEBOOK_GRAPH_VERSION": "REPLACE_WITH_SUPPORTED_VERSION_SUCH_AS_vMAJOR.MINOR",
  "FACEBOOK_PAGE_ACCESS_TOKEN": "REPLACE_WITH_AUTHORIZED_PAGE_ACCESS_TOKEN",
  "MARKETING_AUTOMATION_ENABLED": "true",
  "AUTO_APPROVAL_ENABLED": "true",
  "PUBLISHING_ENABLED": "true",
  "WORKER_ENABLED": "true",
  "DD_API_KEY": "REPLACE_WITH_DATADOG_API_KEY",
  "DD_SITE": "us5.datadoghq.com",
  "DD_LOGS_ENABLED": "true",
  "DD_LLMOBS_ENABLED": "1",
  "DD_LLMOBS_AGENTLESS_ENABLED": "1",
  "DD_LLMOBS_ML_APP": "bun2too-marketing-crew-team",
  "DD_SERVICE": "bun2too-marketing-api",
  "DD_ENV": "production",
  "DD_TRACE_ENABLED": "false"
}
```

| Keys inside `MARKETING_RUNTIME_CONFIG` | Function / requirement |
| --- | --- |
| `MARKETING_API_KEY` | Injected from the standalone GitHub secret before Terraform apply; overrides any legacy JSON value. Must match the n8n credential |
| `LLM_MODEL`, `OPENAI_API_KEY` | Required model selection and provider authorization. Choose an available provider-qualified model; for another provider replace/add its required key name and dependencies. These are not separate GitHub entries read by the workflow |
| `PUBLIC_API_BASE_URL` | Required public article origin; match `CREWAI_BASE_URL`. Facebook links point to `/articles/{run_id}` here |
| `FACEBOOK_PAGE_ID` | Required numeric ID for the authorized target Page. The `bun2too` handle or profile URL does not resolve this ID automatically |
| `FACEBOOK_GRAPH_VERSION` | Required supported version formatted `v<number>.<number>`; configure the version used by your Meta app |
| `FACEBOOK_PAGE_ACCESS_TOKEN` | Required Page access token authorized to publish to that ID; not an app token, Railway token or n8n token |
| `MARKETING_AUTOMATION_ENABLED` | `true` enables scheduled job creation |
| `AUTO_APPROVAL_ENABLED` | `true` allows policy-based approval when the business profile also selects automatic mode |
| `PUBLISHING_ENABLED` | `true` enables real publication. Scheduled generation/readiness rejects disabled or missing delivery configuration |
| `WORKER_ENABLED` | `true` starts the durable scheduled-generation worker; default is true, included explicitly |
| `DD_API_KEY`, `DD_SITE` | Runtime Datadog credentials/site; no automatic inheritance from the standalone GitHub entries |
| `DD_LOGS_ENABLED` | `true` exports durable application and n8n callback events to Datadog Logs |
| `DD_LLMOBS_ENABLED`, `DD_LLMOBS_AGENTLESS_ENABLED` | `1` enables the launcher/integration and direct LLM Observability export |
| `DD_LLMOBS_ML_APP`, `DD_SERVICE`, `DD_ENV` | App/service/environment labels. Change `DD_ENV` to `qa` in QA |
| `DD_TRACE_ENABLED` | `false` disables conventional APM export to a nonexistent local Datadog Agent; LLM Observability uses its separate agentless path |

**Secret: `N8N_RUNTIME_CONFIG`**:

```json
{
  "N8N_ENCRYPTION_KEY": "REPLACE_WITH_THE_EXISTING_N8N_INSTANCE_KEY",
  "WEBHOOK_URL": "https://n8n.bun2too.com/",
  "N8N_EDITOR_BASE_URL": "https://n8n.bun2too.com",
  "N8N_PROXY_HOPS": "1",
  "GENERIC_TIMEZONE": "America/Chicago",
  "TZ": "America/Chicago"
}
```

| Keys inside `N8N_RUNTIME_CONFIG` | Function / requirement |
| --- | --- |
| `N8N_ENCRYPTION_KEY` | Stable key used to decrypt n8n credentials. For the existing instance preserve its actual key from its current environment/configuration; do not replace it with a newly generated key. Generate a new key only for a genuinely new instance |
| `WEBHOOK_URL`, `N8N_EDITOR_BASE_URL` | Public n8n URL with/without the shown trailing slash; use the QA URLs in QA |
| `N8N_PROXY_HOPS` | `1` for the documented single reverse-proxy setup; adjust if the actual proxy chain differs |
| `GENERIC_TIMEZONE`, `TZ` | `America/Chicago` for scheduling/system time with daylight saving; the workflow installer also explicitly uses this timezone |

Terraform supplies `RAILWAY_RUN_UID="0"` for Railway volume write access and defaults `N8N_USER_FOLDER="/home/node"` to preserve the mounted data location. You do not need additional GitHub secrets for these settings.

Persist `/home/node/.n8n` as well as its encryption key. An empty volume mounted over an existing data directory hides its contents; back up, verify restoration and restore the existing data as part of the storage cutover before activating schedules. For an existing service with no volume, `N8N_VOLUME_READY=true` acknowledges this migration; the pipeline refuses to attach an empty volume without it. An existing correct attachment is reused even if the flag is later absent or false. The current MVP uses SQLite persistence; the separate Postgres service is **not automatically connected to n8n**. Changing `DB_TYPE` is not a database migration.

### 5. One-time setup outside the GitHub settings screen

1. **HCP/Railway:** confirm the IDs above, existing production state/import, Local HCP execution mode and persistent storage. Keep CrewAI at one replica with `/data`; QA needs its own CrewAI and n8n volumes. Both service URLs must reach the intended environment.
2. **Generate the marketing key:** locally run `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. Put the generated value in GitHub secret `MARKETING_API_KEY`; CI injects it into the Terraform runtime map.
3. **Create the n8n management API key:** save an owner/admin API key as `N8N_API_KEY`. CI uses the public credential list/create/update APIs to provision `Bun2too Marketing API (production)` (or `qa`) as `httpHeaderAuth` with `Authorization: Bearer <MARKETING_API_KEY>`. It uses the returned ID in both workflow templates, without embedding the secret in workflow JSON. An optional existing credential ID can be adopted; otherwise the named managed credential is reused and updated on later deployments. The old literal `MARKETING_API_KEY` value is repaired by creating/reusing the managed credential. Scoped n8n keys need credential list/create/update permissions in addition to workflow permissions. Older n8n versions lacking these public endpoints require an upgrade or a manually maintained credential; the managed installer reports unsupported endpoints before modifying workflows.
4. **Authorize the destination:** obtain the numeric Facebook Page ID, supported Graph version and a Page token with the required publishing/read access. For production verify the ID is your Bun2too Page; for QA use a test Page. These go inside `MARKETING_RUNTIME_CONFIG`.
5. **Complete the business profile:** edit the committed `crewai_agents/config/marketing.json` with business facts, audience, approved source URLs and brand rules. Keep `approval_mode=automatic`, daily cadence `1440`, `max_posts_per_day=1`, `timezone=America/Chicago`, generation at `08:00` and release window `08:00`–`22:30` for the requested MVP. This file is not a GitHub Variable; placeholders stop scheduled operation. To use a different packaged profile, supply an absolute `MARKETING_PROFILE_PATH` inside the CrewAI JSON and ensure the file exists in the image.

The credential relationships must be exact:

```text
GitHub MARKETING_API_KEY
  = deployed Railway MARKETING_API_KEY (injected by CI)
  = the token after "Bearer " in the saved n8n Header Auth credential

GitHub CREWAI_BASE_URL = MARKETING_RUNTIME_CONFIG.PUBLIC_API_BASE_URL
GitHub DD_SITE = MARKETING_RUNTIME_CONFIG.DD_SITE (for the same Datadog site)
```

### 6. Names you must not configure as extra GitHub entries

The workflow already supplies `DEPLOY_ENVIRONMENT`, `DEPLOY_OPERATION`, `MARKETING_TIMEZONE`, `TF_IN_AUTOMATION`, all `TF_VAR_*` mappings, the provider's `RAILWAY_TOKEN` alias and GitHub's `GITHUB_*` values. Terraform sets CrewAI `DATA_DIR=/data`; **do not add `DATA_DIR` to the runtime JSON**, where it is explicitly rejected. Railway/application defaults handle `PORT` (default 8000).

Standalone GitHub entries named `FACEBOOK_PAGE_ACCESS_TOKEN`, `FACEBOOK_PAGE_ID`, `OPENAI_API_KEY`, `LLM_MODEL`, `DD_ENV`, `DD_LOGS_ENABLED` or `N8N_ENCRYPTION_KEY` are **not consumed** by this workflow. Put them in the appropriate JSON secret above. `MARKETING_API_KEY` is automatically merged into the runtime map from the standalone secret. `DD_API_KEY` and `DD_SITE` still need runtime JSON entries because CI and the runtime use them separately.

`N8N_WEBHOOK_URL` and `N8N_WEBHOOK_TOKEN` belong to the legacy manual dispatch endpoint and are not required for the scheduled MVP. `CREWAI_TRACING_ENABLED`, `AGENT_VERBOSE`, CrewAI cloud credentials, Atlassian/Jira/Confluence settings and email-provider keys are not required for this Facebook MVP. The agents run in Railway; no CrewAI cloud registration is performed.

### 7. Deploy and verify the requested outcome

- [ ] Every required variable and all eight secrets above are set in the selected GitHub environment; both JSON objects are complete and valid.
- [ ] The three copies of the marketing key match, the n8n credential ID is real, and the Facebook ID/token belong to the intended Page.
- [ ] The business profile is complete; HCP state and both persistent application data directories are prepared without losing existing data.
- [ ] Run `.venv/bin/python scripts/verify_marketing.py --terraform` locally before committing the reviewed revision.
- [ ] Run **Actions → Infrastructure and Core Deployment Pipeline → Run workflow → operation `deploy`** on `main` or `qa`. A push to either branch also requests full deploy. `infrastructure-only` applies Terraform without uploading CrewAI/installing workflows; `import-state` on main imports and plans without applying.
- [ ] GitHub's summary contains workflow IDs/links and shows `[production] Marketing daily operations` (or QA equivalent) active. Its error-handler workflow is referenced and does not require its own active schedule.
- [ ] Within five minutes, inspect n8n Executions and authenticated `/automation/status`. Polls outside the generation window may correctly return `not_due`; repeat polls reuse the day's run.
- [ ] Verify a real Facebook post ID, its reachable article URL and later engagement observations. In Datadog verify app logs/LLM activity and the separate deployment log. A green deployment alone does not prove a successful model call or Facebook publication.

<!-- END GITHUB MVP CONFIGURATION -->

## Current deployment and implementation status

The n8n UI is [n8n.bun2too.com](https://n8n.bun2too.com/). Railway also has [crewai.bun2too.com](https://crewai.bun2too.com/) configured; its `/health` responded successfully during inspection. The 2026-09-23 inspection found an older CrewAI app without `/ready` and missing runtime configuration; this is a historical observation, not a current deployment status check. A running container is not yet an operating marketing team.

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
