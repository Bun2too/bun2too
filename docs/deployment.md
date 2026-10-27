# Production and QA deployment

Use this document to configure the complete MVP from one checklist. The GitHub configuration block is also included in README.md; keep those two copies identical. Historical infrastructure troubleshooting follows the checklist.

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
| `RAILWAY_API_TOKEN` | Railway account/workspace API token with access to the project/environment | Railway API, Terraform provider and CLI upload; Terraform receives it through its explicit token input |
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
| `FACEBOOK_PAGE_ACCESS_TOKEN` | Required authorized Page token, or an authorized user token with existing grants to obtain that exact Page's token. Runtime verifies the resolved Page identity and own-post read access; never use an app token, Railway token or n8n token |
| `MARKETING_AUTOMATION_ENABLED` | `true` enables scheduled job creation |
| `AUTO_APPROVAL_ENABLED` | `true` allows policy-based approval when the business profile also selects automatic mode |
| `PUBLISHING_ENABLED` | `true` enables real publication. Scheduled generation/readiness rejects disabled or missing delivery configuration |
| `ARTICLE_ARTWORK_ENABLED` | Optional, defaults to `true`. Generates one persistent editorial hero for each approved scheduled article and backfills the latest public article after the first upgraded deployment |
| `ARTICLE_IMAGE_MODEL` | Optional GPT Image model; defaults to `gpt-image-2.5-flare` |
| `ARTICLE_IMAGE_QUALITY` | Optional `low`, `medium`, or `high`; defaults to `medium` |
| `ARTICLE_IMAGE_SIZE` | Optional `1024x1024`, `1536x1024`, or `1024x1536`; the editorial default is `1536x1024` |
| `ARTICLE_IMAGE_TIMEOUT_SECONDS` | Optional 30–600 second request bound; defaults to `240` |
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

## n8n persistence, recovery and first deployment

n8n's default SQLite database lives at `/home/node/.n8n/database.sqlite`. It contains owner/admin accounts, login configuration, API keys, workflows and credential records. Keeping only `N8N_ENCRYPTION_KEY` does not keep this database. The separate Postgres service is not used by n8n unless a deliberate database migration configures it. See [n8n Docker persistence](https://github.com/n8n-io/n8n-docs/blob/main/docs/deploy/host-n8n/install-options/install-with-docker.md).

Before Terraform plan/apply, `scripts/ensure_n8n_volume.py` verifies or creates a volume at `/home/node/.n8n` using explicit project, environment and service IDs. It reuses existing attachments, rejects wrong mount paths or recognizable orphaned volumes, and reads back a newly created attachment before continuing. Both production and QA use this environment-scoped path. Terraform ignores changes to the n8n service's nested `volume` attribute so provider v0.6.2 cannot create or remove that externally managed attachment. The attachment is checked again before and after apply. The workflow saves a Terraform plan, checks it, and applies that exact plan. The check rejects deleting/replacing the n8n service, moving/removing its volume, deleting its runtime collection, and changing/removing its tracked encryption key or database location. It also compares supplied protected settings with the current Railway service variables to cover keys not yet recorded in state. It never prints variable values or plan JSON. A key stored only in the container config cannot be compared through the Railway variables API; preserve that key during initial adoption. A new attachment in either environment requires `N8N_VOLUME_READY=true`; existing attachments do not.

### n8n crashes with EACCES after attaching storage

`EACCES: permission denied, open '/home/node/.n8n/config'` means the process cannot write its mounted configuration directory. A repeated startup crash can surface as HTTP 502 in the workflow installer. Railway mounts volumes as root and documents `RAILWAY_RUN_UID=0` for images running as a non-root user ([Railway volume permissions](https://docs.railway.com/volumes#permissions)).

The n8n runtime collection now injects `RAILWAY_RUN_UID="0"` and defaults `N8N_USER_FOLDER` to `/home/node`. The explicit user folder keeps the database and configuration under the existing `/home/node/.n8n` mount even when the process runs as root. Existing explicit user-folder settings remain subject to the storage migration guard. The encryption key and database are not regenerated by this change.

For immediate recovery of the standard configuration, set **both** variables on the existing Railway n8n service in the affected environment and deploy those variable changes. Keep the current volume and encryption key. This runs n8n as root inside the container; it does not change the volume's ownership. Confirm startup logs no longer show EACCES, `/healthz` returns HTTP 200, and the existing owner login and management API key work before rerunning workflow installation. HTTP 200 health alone does not verify account/database preservation. If owner setup appears, follow the recovery section below rather than assuming the old data was recovered.

### Provider volume read-back failure

If an older run reports `Provider produced inconsistent result after apply` with `.volume ... now null`, do not delete the service or remove its Terraform state. Provider v0.6.2 creates nested service volumes without passing an environment ID, then reads volume instances in the default environment ([provider implementation](https://github.com/terraform-community-providers/terraform-provider-railway/blob/v0.6.2/internal/provider/resource_service.go)). The error alone does not distinguish a delayed attachment from an environment mismatch. The new scoped provisioner bypasses this path and waits for the attachment to become visible. A failed create may already have left a volume behind; the provisioner reuses a correct attachment and refuses to replace an identifiable unattached n8n volume. If it reports an orphan, inspect/reattach that volume in Railway after confirming its data and target environment. It never deletes volumes or retries a creation mutation blindly.

### If the owner setup screen reappears

Pause deployments and inspect the selected Railway environment, n8n volume attachment and database location before creating another owner. The screen means n8n is seeing an uninitialized database; it does not prove that the old database has been deleted. An absent/wrong volume, a changed database path, or a fresh external database can produce the same symptom.

- If an old volume or backup exists, restore the original database and matching encryption key. Preserve the entire `.n8n` directory. For SQLite, use a consistent backup or stop writes before copying the directory, including any WAL files; copying a live `database.sqlite` alone may omit recent data.
- If the old container still exists without persistent storage, back up its `.n8n` directory before another deployment. Do not mount an empty volume over the only recoverable copy.
- If the old database existed only on discarded ephemeral storage and no backup survives, CI cannot recover the former accounts or API keys. Establish persistent storage, then set up the owner and credentials once again.

An existing service with no volume needs a controlled migration: prepare a backup and restore procedure (or verify it is empty), set `N8N_VOLUME_READY=true`, apply infrastructure, restore data before use, and verify the owner login and existing API key. Keep the same `N8N_ENCRYPTION_KEY`. Enable Railway volume backups and verify a restore separately. No automatic recovery or backup is implied by creating a volume.

### First-time bootstrap

1. Configure Railway/HCP targets and the runtime JSON maps. For a genuinely new n8n instance, generate a stable encryption key once and include it in `N8N_RUNTIME_CONFIG`. Do not replace a key belonging to an existing database.
2. Run the workflow manually with **operation=infrastructure-only**. This provisions persistent infrastructure without requiring `N8N_API_KEY`, installing workflows, or activating schedules. If the Railway service already exists but is empty and unpersisted, set the migration acknowledgement described above.
3. Confirm the production n8n volume is mounted at `/home/node/.n8n` (and the separate QA attachment when applicable). Complete owner setup in n8n, then create a management API key under **Settings → n8n API**. Save it as the selected GitHub environment's `N8N_API_KEY`. The full deployment provisions its separate Header Auth credential automatically.
4. Run **operation=deploy**. Ordinary updates reuse the same database and encryption key, so owner setup and API-key creation are not repeated. Confirm the existing login and workflow API still work after the first subsequent redeployment.

The current workflow does not automate owner creation or API-key issuance. n8n's documented initial API-key flow requires an authenticated owner/admin UI session. Newer n8n versions offer `N8N_INSTANCE_OWNER_MANAGED_BY_ENV`, but it overwrites owner details on every startup and is deliberately not enabled for existing instances. See [owner environment settings](https://github.com/n8n-io/n8n-docs/blob/main/docs/reusable-content/.gitbook/includes/self-hosting/configuration/environment-variables/settings-env-vars/instance-owner.md) and [API-key creation](https://github.com/n8n-io/n8n-docs/blob/main/docs/connect/n8n-api/authentication.md).

GitHub environment secrets can be written through its API with an appropriately authorized GitHub App or personal access token. The workflow's `GITHUB_TOKEN` has `contents: read` and cannot write them. Automatic secret saving would require separately provisioned environment-secret write access; it is not a zero-credential bootstrap. From an authenticated local GitHub CLI, `gh secret set N8N_API_KEY --env production` prompts for the value without putting it in command arguments. Do not paste keys into workflow logs. See [GitHub environment-secret API](https://docs.github.com/en/rest/actions/secrets#create-or-update-an-environment-secret).


## Log investigation: `logs.1790026057842.log`

This file contains Postgres entrypoint errors from **2026-09-20 19:20:54–19:21:02 UTC**, not an n8n startup trace. It is byte-for-byte identical to the earlier `logs.1789932611704.log` export (SHA-256 `549dcef4c738100f952dbfa49880459bb7340e12d3e809224a74fd249894fdfb`). Downloading it again did not capture a newer deployment.

The demonstrated cause is a missing or empty `POSTGRES_PASSWORD` when an uninitialized Postgres container starts. It exits and Railway repeatedly restarts it. This log cannot establish why the secret was absent or whether the current deployment still has the problem. The repository already maps the selected GitHub environment's `POSTGRES_PASSWORD` secret through `TF_VAR_postgres_password` to the selected Railway Postgres service/environment. A local CrewAI `.env` value does not configure that separate service.

CI now reads back Railway's rendered Postgres password configuration **after Terraform apply** and fails if it is missing, empty or differs from the GitHub secret. Values and API response bodies are never printed. This requires an API-readable value, as used by the existing Terraform variable resource; sealed variables cannot be verified by this check. A successful readback verifies configuration only, not database readiness, deployment completion or authentication against an already initialized cluster. See [Railway's variables API](https://docs.railway.com/integrations/api/manage-variables).

To resolve and confirm this incident:

1. Check that the intended GitHub environment has a non-empty `POSTGRES_PASSWORD`, that `POSTGRES_SERVICE_ID` points at the database, and that `RAILWAY_ENVIRONMENT_ID` points at the correct environment. Complete the HCP state migration/import below if Terraform apply is blocked.
2. Run the branch's deployment workflow and confirm both Terraform apply and **Verify Postgres password reached Railway** pass. Alternatively, use the immediate Railway repair below.
3. In Railway, select that environment and the Postgres service's **latest deployment**. Deploy any staged variable changes and confirm fresh logs show `database system is ready to accept connections`.
4. Select `n8n-orchestrator` separately and inspect its latest deployment logs and image source. Terraform configures its image as `docker.io/n8nio/n8n:latest`. If the supplied Postgres messages really came from this service, verify that its deployed image is not accidentally Postgres. Capture the service name, environment and deployment timestamp with any remaining n8n error. This export does not establish an n8n-specific cause.

## Repair the crashed Postgres service

The supplied log reports: `Database is uninitialized and superuser password is not specified.` The `postgres:15-alpine` image requires a non-empty `POSTGRES_PASSWORD` when initializing an empty database.

For immediate recovery, open the existing Railway project, select **production**, and open `pipeline-postgres` (service ID `dd68258c-7986-46e8-b8a7-e2830403ba17`). Before restarting this uninitialized database:

1. Attach a persistent volume at `/var/lib/postgresql/data` if none exists. Keep an existing volume; do not delete it.
2. In service Variables set:
   - `POSTGRES_PASSWORD`: a strong random password, also saved as the production GitHub environment secret of the same name.
   - `POSTGRES_USER`: `postgres` (or your chosen initial administrator).
   - `POSTGRES_DB`: `bun2too` (or your chosen initial database).
   - `PGDATA`: `/var/lib/postgresql/data/pgdata` for the new, empty volume.
3. Deploy the staged changes/redeploy the service. Verify its logs reach `database system is ready to accept connections` and verify a password-authenticated connection.

Do not set `POSTGRES_HOST_AUTH_METHOD=trust`. These initialization variables do not change passwords, users or database names in an already initialized cluster. If the database has since initialized, preserve its existing `PGDATA` and volume contents, and perform any password change with SQL plus corresponding client-secret updates. Do not point an existing populated database at a new empty data directory.

Terraform now configures these four variables for the selected environment and manages the production volume. The QA volume needs the one-time setup below because this provider's service/volume resource reads the project's default environment, not an arbitrary QA environment. `prevent_destroy` protects the production Postgres service in Terraform; it is not a backup mechanism.

Source: [official Postgres image documentation](https://github.com/docker-library/docs/blob/master/postgres/README.md).

## Railway setup: one project, two environments

Use the project from the supplied link: `f5a4899e-a958-4353-b6a3-99a57b80ebad`. Its production environment ID is `72e3af2d-37a3-430f-92ed-e0941b0b6435`.

1. Keep its default environment named `production`.
2. Create `qa` in the same project. Duplicate service configuration into QA if needed, then inspect all inherited variables. Use a **separate empty QA Postgres volume**, mounted at `/var/lib/postgresql/data`, and a different database password. Do not restore production data into QA as part of this setup.
3. Ensure the QA Postgres instance uses `postgres:15-alpine`. Ensure the QA CrewAI instance has root directory `crewai_agents`. Record the QA environment ID and the service IDs shown in that environment.
4. Disable Railway GitHub autodeploy triggers for CrewAI in both environments; this workflow uploads the checked-out branch. Production Terraform removes the old project-level GitHub source connection. This avoids an inherited `main` trigger deploying production code into QA.
5. Configure the two GitHub runtime JSON secrets using the complete checklist above; Terraform writes their fields into each selected Railway service/environment. Full scheduled QA deployments need an authorized test Page and enabled delivery. Use manual drafts when publishing is disabled.
6. Configure n8n/database connections separately if using them. This change initializes Postgres; it does not migrate n8n to Postgres or automatically wire application clients to it.

Production Terraform owns the shared project/service definitions. QA Terraform owns its environment-specific variables (Postgres, CrewAI and configured n8n runtime settings); it cannot create, delete or update shared services. A production change to a shared Railway service can affect both instances, because the provider can redeploy all instances. The workflow serializes both branches' deployments within the repository.

## Pipeline API calls and preflight diagnostics

The preflight makes exactly two requests, in order, stopping at the first failure:

1. `GET https://app.terraform.io/api/v2/organizations/{TF_CLOUD_ORGANIZATION}/workspaces/{TF_WORKSPACE}` with `Authorization: Bearer $TF_API_TOKEN`. For production this is `https://app.terraform.io/api/v2/organizations/Bun2tooinc/workspaces/code-monkey-army`. It requires `data.attributes.execution-mode` to be `local`.
2. `POST https://backboard.railway.com/graphql/v2` with `Authorization: Bearer $RAILWAY_API_TOKEN` and `Content-Type: application/json`. The exact body for the configured project is:

   ```json
   {
     "query": "query($id: String!) { project(id: $id) { environments { edges { node { id name } } } services { edges { node { id } } } } }",
     "variables": {"id": "f5a4899e-a958-4353-b6a3-99a57b80ebad"}
   }
   ```

HTTP success alone is insufficient: Railway must return a project with no GraphQL errors, the selected environment ID must have exactly the name `production` or `qa`, and both distinct service IDs must belong to that project. Before either request, the script checks branch/environment mapping and the configured workspace name and required nonempty inputs. `POSTGRES_PASSWORD` is only checked for presence during preflight; it is not sent to either API.

The HCP workspace GET does **not** require an organization token. A team token can access workspaces granted to its team; a user token inherits the user's permissions, subject to organization policy. Use a team token with access to the selected workspace and state read/write plus locking permissions for this Local execution workflow. An organization token succeeding where a team token failed does not establish that the endpoint requires an organization token. Organization tokens are intended for administrative setup, and cannot start remote runs or create configuration versions. See [HCP token types](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/api-tokens) and [workspace permissions](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/permissions/workspace).

Railway must use an account/workspace token here. Project tokens use a different header (`Project-Access-Token`) and are not supported by this script's bearer authentication. See [Railway API authentication](https://docs.railway.com/integrations/api).

Later pipeline operations are separate from these two checks:

| Step | External access |
| --- | --- |
| Terraform setup/init | Installs Terraform/provider packages; the same `TF_API_TOKEN` is installed as Terraform's HCP credential for workspace/state access. |
| Terraform state list/apply | HCP state reads, locking, writes/unlocking; Railway provider reads and mutations for resources in `terraform/main.tf`, authenticated with the same Railway secret mapped to the provider's `RAILWAY_TOKEN`. Exact calls depend on the plan and provider implementation. Production must already have imported/migrated shared resources in state. |
| Postgres verification | Railway GraphQL `variablesForServiceDeployment(projectId, environmentId, serviceId)` reads the selected Postgres variables and compares the password locally without printing values. |
| Railway CLI deployment | `python3 -m scripts.deploy_crewai` uploads with `railway up --detach --json`, then polls the returned deployment ID until Railway reports `SUCCESS` (15-minute status deadline). Failed deployments stop the pipeline before HTTP readiness. |

The updated workflow logs `Deployment checkout: <commit>` and `Deployment diagnostics v3`, then a `Checking`/`Passed` line for each API check. Failures identify the operation and HTTP status, network/JSON failure, missing schema field, or failed validation without logging tokens or response bodies. If these markers are absent, the run is using an older workflow/script. Re-running an older GitHub Actions run uses its original revision; deploy a commit containing these changes on the intended branch.

To reproduce the exact production preflight locally, set `TF_API_TOKEN`, `RAILWAY_API_TOKEN`, and `POSTGRES_PASSWORD` to the same values as the GitHub **production environment** secrets, then run from the repository root:

```sh
GITHUB_REF_NAME=main \
DEPLOY_ENVIRONMENT=production \
TF_CLOUD_ORGANIZATION=Bun2tooinc \
TF_WORKSPACE=code-monkey-army \
RAILWAY_PROJECT_ID=f5a4899e-a958-4353-b6a3-99a57b80ebad \
RAILWAY_ENVIRONMENT_ID=72e3af2d-37a3-430f-92ed-e0941b0b6435 \
POSTGRES_SERVICE_ID=dd68258c-7986-46e8-b8a7-e2830403ba17 \
CREWAI_SERVICE_ID=8eefe858-998d-4887-9f5c-bcacc5a16e3a \
python3 scripts/check_deployment.py
```

GitHub environment secrets override repository secrets with the same name. Updating a repository token alone may leave an older production environment token in use. A local pass also does not verify runner network access or subsequent Terraform write permissions.

## HCP Terraform and existing infrastructure

Use separate state workspaces for production and QA. You do not need workspaces named `bun2too-production` or `bun2too-qa`.

For the existing account, keep `TF_CLOUD_ORGANIZATION=Bun2tooinc`. Set the production GitHub environment's `TF_WORKSPACE=code-monkey-army` **if that workspace is the production state owner**. Inspect its state first; the workspace URL alone does not establish its contents. Create/select a separate QA workspace, for example `code-monkey-army-qa`, and set that name in the QA GitHub environment. Never point both environments at the same workspace. Set `TF_WORKSPACE` at environment scope rather than providing a shared repository default.

For a consistent convention across applications, use:

| HCP level | Convention | Example |
| --- | --- | --- |
| Organization | Company/account | `Bun2tooinc` (or `bun2too` if deliberately renamed in HCP) |
| Project | Application or infrastructure grouping | `code-monkey-army` |
| Workspace | `<application>-<environment>[-<region>][-<component>]` | `code-monkey-army-production`, `code-monkey-army-qa` |

HCP workspace names are unique across the **organization**, not just their project. Bare `production` and `qa` would prevent another HCP project in the same organization from using those names. An HCP project groups workspaces and permissions; it does not add a namespace to the workspace lookup URL. The project name is not needed by this workflow's explicit organization/workspace selection. See [HCP workspace naming](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/create).

An existing production workspace can retain `code-monkey-army` or be renamed in HCP to `code-monkey-army-production`, with the GitHub variable updated afterward. Preserve the existing state; creating an empty replacement workspace does not move resource ownership. Moving it into an HCP project is organizational and should keep that same workspace/state.

Add a region suffix only when a workspace owns independently deployed regional resources. Naming a workspace for a region does not configure Railway placement. This workflow still deploys one target per branch; simultaneous regional deployments would need explicit target mappings and separate resource ownership. In particular, the current production Terraform owns shared project/service definitions, so do not run copies of it in multiple regional workspaces against the same resources.

Set **Execution Mode → Local** on both. GitHub Actions executes Terraform with that environment's credentials; HCP stores and locks state. The preflight checks the execution mode. Do not connect these workspaces to a second VCS-driven apply workflow. Limit access to state: it contains database passwords despite Terraform marking them sensitive.

The `cloud {}` configuration selects the organization via `TF_CLOUD_ORGANIZATION` and the workspace via `TF_WORKSPACE`. CI reads the workspace name from the selected GitHub environment; it does not derive or enforce a naming convention. Local Terraform operations must set the same variables explicitly.

### One-time production state migration/import

The previous workflow used ephemeral local state. **Do not apply against an empty production HCP workspace:** it would create duplicate resources. CI now refuses to apply until all four existing shared resources are present in production state.

The error `No state file was found!` after successful init/validate means the selected workspace has no state yet. `terraform init` connects to HCP; it does not discover or adopt existing Railway resources. The workflow now reports this explicitly instead of exiting before the import guidance.

For an existing Railway deployment without recoverable Terraform state, use the built-in bootstrap:

1. Put the updated workflow/scripts on `main` (the workflow must also be on the repository's default branch for GitHub's manual-run button).
2. In **Actions → Infrastructure and Core Deployment Pipeline → Run workflow**, select branch **main** and operation **import-state**.
3. The workflow uses the production environment's existing credentials and target IDs. It discovers the unique service named `n8n-orchestrator`; if your existing n8n service has another name, set production variable `N8N_SERVICE_ID` to its ID. It validates that all three services belong to the selected project before any import.
4. It imports the project, Postgres, CrewAI, n8n, and existing managed Postgres/CrewAI variables into the selected HCP workspace. It skips addresses already tracked, so a partially completed import can be resumed. No apply or application deployment runs in this mode.
5. Review the resulting Terraform plan, especially database volume/PGDATA and service source changes. Once the plan is appropriate, run the workflow on main with operation **deploy**.

Importing writes Terraform state and requires HCP state-write/locking permissions. It does not recreate infrastructure or migrate database data. If these resources are already owned by another state/workspace, migrate that state instead of importing them into a second owner. The same Railway resource must not be managed by two state files. Authentication/backend/network errors reading state are not treated as an empty workspace.

If you have the original state, back it up securely and run `terraform init` locally with `TF_WORKSPACE=code-monkey-army` to follow HCP's migration prompts. The `moved` blocks preserve the original resource addresses when adding the production-only resource counts.

If the old runner's state is lost, import the existing resources into `code-monkey-army`. From the repository root:

```sh
export TF_CLOUD_ORGANIZATION='YOUR_HCP_ORGANIZATION'
export TF_WORKSPACE='code-monkey-army'
terraform login
cp terraform/production.tfvars.example terraform/production.tfvars
```

Fill the non-secret IDs/repository values in that ignored tfvars file. Supply `RAILWAY_TOKEN` and `TF_VAR_postgres_password` securely in your shell, then:

```sh
terraform -chdir=terraform init
terraform -chdir=terraform import -var-file=production.tfvars 'railway_project.fb_pipeline[0]' f5a4899e-a958-4353-b6a3-99a57b80ebad
terraform -chdir=terraform import -var-file=production.tfvars 'railway_service.postgres_db[0]' dd68258c-7986-46e8-b8a7-e2830403ba17
terraform -chdir=terraform import -var-file=production.tfvars 'railway_service.crewai_service[0]' YOUR_CREWAI_SERVICE_ID
terraform -chdir=terraform import -var-file=production.tfvars 'railway_service.n8n_engine[0]' YOUR_N8N_SERVICE_ID
terraform -chdir=terraform plan -var-file=production.tfvars
```

Review the plan for the existing project and services. It should add/adopt the Postgres configuration and persistent volume, and disconnect the old CrewAI GitHub source; it should not recreate the project or database. If variables already exist in Railway, import them before applying, using the provider's `service-id:environment-name:variable-name` import format. Example:

```sh
terraform -chdir=terraform import -var-file=production.tfvars railway_variable.postgres_password dd68258c-7986-46e8-b8a7-e2830403ba17:production:POSTGRES_PASSWORD
terraform -chdir=terraform import -var-file=production.tfvars 'railway_variable.postgres_config["PGDATA"]' dd68258c-7986-46e8-b8a7-e2830403ba17:production:PGDATA
```

Import `POSTGRES_USER` and `POSTGRES_DB` similarly. In QA, import existing variables into the QA workspace with its environment name if already configured; no shared project/service resources belong in QA state. Use QA-specific input values when importing there.

After HCP state setup, push the updated workflow to `main`, then merge it into `qa` and push that branch. The workflow verifies targets, applies the selected environment's Terraform, then uploads CrewAI to that Railway environment. The upload step waits for the exact new deployment to reach Railway `SUCCESS` before `/ready` is checked and n8n schedules are installed. No running CrewAI API is required before configuration and upload. A readiness failure leaves the uploaded deployment in Railway for diagnosis; it does not roll back configuration or code. Inspect Postgres runtime logs separately to confirm database health.

References: [HCP configuration/state migration](https://developer.hashicorp.com/terraform/cli/cloud/settings), [GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments), [Railway provider variable import](https://github.com/terraform-community-providers/terraform-provider-railway/blob/v0.6.2/docs/resources/variable.md).

## Reading deployment traces

Each run records the commit, run ID/attempt, branch, selected environment, HCP organization/workspace, and Railway target IDs. Credential diagnostics report presence only. Preflight logs contain UTC timestamps, API method/URL, authentication scheme with a redacted token, the read-only GraphQL query and allowlisted target arguments, HTTP status, request duration, and validation results. HCP mode/inheritance and Railway environment/service matches are reported explicitly. Raw response bodies, GraphQL error messages, Postgres variable values, and Terraform state contents are excluded.

Pipeline shell commands run through `scripts/run_deployment_step.py`, which logs the command, working directory, start time, duration, and exit code while preserving the command's failure status. Normal tool output remains in GitHub's masked step logs. Terraform, Node, and Railway CLI versions are recorded. Terraform state-list output is captured privately by the state preparation script; missing required addresses are named on failure. Third-party setup actions retain their standard GitHub step logs. No shell `set -x`, environment dump, or Terraform provider debug logging is enabled.

Open the GitHub Actions run's job steps for detailed output; the run summary lists command outcomes and the final job status even after an earlier failure (subject to runner availability). These traces apply to runs using the updated commit; they cannot add detail retroactively to old runs. Provider/CLI internal HTTP traffic is not captured by this wrapper.

### Railway HTTP 403 despite a successful local request

A 403 occurs before the script can validate Railway's environment/service response. It does not by itself prove an invalid token. Compare the exact GraphQL query/project ID and authentication header with the successful request. This script uses `Authorization: Bearer` for an account/workspace token; a Postman request using `Project-Access-Token` is a different authentication mechanism. Also ensure the production GitHub environment secret matches the locally tested credential.

Requests now send `Accept: application/json` and the explicit user agent `crew-team-deployment-preflight/1.0`. This removes reliance on Python's default user agent; it is not a confirmed fix for a particular 403. Response logs include only allowlisted headers: content type, server, Cloudflare ray/mitigation headers, request ID, and retry-after. An HTML response or challenge header helps investigate a gateway rejection. A Cloudflare server/ray header alone does not prove Cloudflare blocked the request. Use the timestamp and request ID when investigating with Railway support. Cookies, raw bodies and tokens remain excluded.

### State inspection diagnostics

The state check runs `terraform state list -no-color` and also strips ANSI escapes defensively. Terraform can otherwise prefix its missing-state message with a color escape, which caused the earlier exact-prefix check to misclassify an empty workspace as a backend failure. On failure, redacted stdout/stderr are recorded as JSON diagnostic fields. Actual permission/network errors still stop the run.

The log records `operation=deploy` or `operation=import-state`. A command ending in `prepare_terraform_state.py` without `--import-existing` only checks state; it does not import resources. For initial adoption, manually run the workflow on main with `operation=import-state`, review the plan, then run `deploy`.

## Runtime Datadog delivery diagnostics

`DD_LOGS_ENABLED=true` exports CrewAI journal events; it does not forward every Railway/n8n console message. `DD_LLMOBS_ENABLED` controls a separate LLM Observability integration, which requires actual model activity. Runtime values come from `MARKETING_RUNTIME_CONFIG`; the standalone GitHub `DD_API_KEY` and `DD_SITE` configure deployment-outcome logs separately.

The worker records `runtime_started` on startup and attempts delivery even before the first scheduled campaign. Authenticated `GET /observability/status` reports `logs_enabled`, `api_key_configured`, `site`, `site_supported`, `service`, `pending_batch_count` (up to 50), and `last_export`. Export state is per process and resets on restart. It reports intake acceptance, not confirmation that a log is indexed in the UI. Failed batches stay queued; Railway logs include the HTTP status without response bodies or credentials.

Use the marketing Bearer key and explicit client User-Agent, as with `/automation/status`. In Datadog, search `service:bun2too-marketing-api` (or configured `DD_SERVICE`) for runtime events and `service:bun2too-deployment` for CI outcomes, in the account/site matching the relevant `DD_SITE`. If both the schedule and error-handler credentials are missing, neither can call CrewAI's `/automation/events`, so those execution failures never enter the runtime log journal. Repairing the shared credential fixes that reporting path; it does not by itself verify Datadog credentials or ingestion.

## Enterprise OTLP telemetry

The runtime configuration map accepts the settings in [the telemetry implementation guide](telemetry-implementation.md). The Collector and its backend stores are separate infrastructure; the current Railway Terraform does not provision them. Configure and verify the endpoint, authentication, durable queue volume, host signals and alert route before enabling `TELEMETRY_ENABLED=true` in a production runtime map. The [architecture standard](enterprise-ai-observability-architecture.md) defines acceptance requirements and optional Kafka/Event Hub buffering.

## Missing Railway deployment source during Terraform apply

The October 27, 2026 failure occurred after the CrewAI variable collection update, when the provider requested `serviceInstanceRedeploy`. Railway reported that the previous deployment source was no longer available. The successful authenticated checks and variable mutation distinguish this failure from token rejection; the log does not establish why Railway lost the source. Variables may already have changed even though Terraform apply failed.

The pinned Railway provider 0.6.2 automatically redeploys variable collections and exposes no skip-deployment setting ([provider schema](https://github.com/terraform-community-providers/terraform-provider-railway/blob/v0.6.2/docs/resources/variable_collection.md)). CI now installs the Railway CLI before apply. `scripts/apply_terraform.py` recognizes only a single missing-source error from the CrewAI variable collection during a full `deploy`. It uploads the checked-out source using `deploy_crewai.py`, waits for that exact deployment to succeed, creates a fresh plan, reruns the n8n storage/key guard, and retries apply once. It does not reuse a partially applied plan or suppress errors. The normal final application upload, runtime readiness check and workflow installation still follow successful reconciliation.

Commit this fix and run the full `deploy` workflow from the updated main/qa revision. Rerunning the old failed GitHub run uses the old workflow. No service recreation, state deletion, volume replacement or further token rotation is needed for this error. An infrastructure-only operation never uploads application code and still fails explicitly if its variable update encounters a missing source; use a full deployment for recovery. Missing n8n sources, multiple Terraform errors, failed uploads, failed replans, failed storage checks and a failed retry all stop the job for investigation. Recovery can start the new application before Terraform reconciliation finishes, so a failed CI result can coexist with a new running application; inspect the exact deployment and complete reconciliation before declaring success.

### Recovery upload authentication (October 27 follow-up)

The 15:31 UTC run entered the missing-source recovery, but `railway up` immediately exited with `CalledProcessError`. The previous handler hid its reason. Inspection found that recovery inherits both `RAILWAY_TOKEN` and `RAILWAY_API_TOKEN` from the Terraform step. Terraform uses the former for the account token; the [Railway CLI prioritizes it as a project-access token](https://github.com/railwayapp/cli/blob/master/src/client.rs), even when the correct account-token variable is also present. This is a concrete authentication-mode defect; the historical CLI stderr was not retained in the provided log, so its precise message cannot be recovered from that log.

`deploy_crewai.py` now passes an explicit child environment with `RAILWAY_TOKEN` removed and `RAILWAY_API_TOKEN` retained. Terraform's environment remains unchanged. The helper reports target IDs, account-token authentication, the returned deployment ID, and safe error categories/exit codes without dumping CLI output or credentials. This applies to both recovery and normal uploads. Tests reproduce the inherited dual-token environment.

The unavailable object is the previous CrewAI deployment's rebuild source, not a missing Terraform service or n8n volume. The affected service is `8eefe858-998d-4887-9f5c-bcacc5a16e3a` in production environment `72e3af2d-37a3-430f-92ed-e0941b0b6435`. The error does not include the old deployment ID or distinguish a missing archive from another inaccessible build source. Terraform refresh can verify service/variable existence without proving that an old deployment remains rebuildable. Recovery uploads fresh source rather than recreating infrastructure. Confirm success on a new full deployment from the fixed revision; local tests alone do not verify live upload authorization.


### Canonical Railway credential convention

Use one GitHub environment secret named `RAILWAY_API_TOKEN` containing an account/workspace token authorized for the target project. Local deployment tools use the same name. CI passes this secret directly as `RAILWAY_API_TOKEN` to the API/CLI, and as `TF_VAR_railway_api_token` to Terraform's sensitive input bound to `provider.railway.token`. This uses the provider's supported configuration instead of exporting `RAILWAY_TOKEN`; there is no second stored secret or token conversion. For manual Terraform commands, supply `TF_VAR_railway_api_token` through your secret manager/environment as well. Mock-provider tests use a dummy token.

Reserve `RAILWAY_TOKEN` for actual Railway project tokens in other projects that deliberately use that authentication type. Do not populate it with an account token. The CrewAI and n8n application runtimes do not need this deployment credential merely because they run on Railway. This repository change does not modify secrets in external projects, GitHub settings, or local ignored environment files. Production and QA may use different authorized token values while sharing this naming convention.

Deployment-history diagnosis needs read access to the selected project/environment/service deployment records (IDs, status, timestamps), not write access or an additional dedicated history secret. A GraphQL error alone does not prove a missing permission: verify token validity, target access and query schema before requesting wider access. Local `.env` credentials are independent of GitHub environment secrets.
