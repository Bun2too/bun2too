# Marketing MVP deployment and operating runbook

Read [the architecture specification](marketing-mvp-architecture.md) for component/agent contracts, the flow diagram, state machine, business rules and failure semantics.

## What a complete deployment creates

Creating Railway services completes only the infrastructure layer:

| Layer | Deployment action | Visible evidence |
| --- | --- | --- |
| Infrastructure | Terraform manages services, variables and configured volumes | Railway services/volumes and HCP state |
| CrewAI application | Railway builds/runs the Python API and worker | Authenticated `/ready`; run IDs and role outputs under `/runs` |
| Scheduled marketing | Installer creates/updates and activates the n8n workflow JSON | `[production] Marketing daily operations` in n8n, active state and execution history |

The old pipeline skipped the last layer when `MARKETING_DEPLOY_ENABLED` was missing or false. Its code could therefore report success with only services deployed; a particular past run must be checked against its step log and revision. Normal `deploy` now requires the workflow inputs, checks readiness, and reads the workflows back after installation. GitHub's summary includes their IDs, links and active states. This verifies application/schedule deployment, not a successful real model call or Facebook post.

The runtime sequence is:

```text
n8n Schedule Trigger: 08:05 America/Chicago
  → CrewAI API /automation/tick reserves the daily campaign
  → Railway worker runs nine roles; Editor edits before Tester reviews
  → n8n persists 15-minute waits, at most six generation checks
  → approved run waits for its persisted publication time
  → /automation/publish sends once within the release window

Separate service-health workflow: every six hours at :15
  → bounded health check and configured fallback alerts

n8n Schedule Trigger: 07:45 America/Chicago
  → /automation/metrics
  → observations inform the next campaign
```

The schedules live inside n8n and use America/Chicago. The API enforces daily deduplication and the 08:00–22:30 Central window. Activation does not imply a run within five minutes: the next daily trigger starts generation. See [bounded orchestration](operational-recovery.md#daily-orchestration-and-bounded-checks) for wait exhaustion and recovery.

**Why no agents appear in the CrewAI account:** this repository uses the CrewAI Python framework inside Railway. `Agent`, `Task` and `Crew` objects are constructed in `crewai_agents/app/crews.py` for each execution. That does not register a hosted deployment in CrewAI AMP. Optional CrewAI tracing is also separate from hosting. Running in the CrewAI cloud account would require an AMP deployment and authenticated kickoff/status integration, which are not implemented here. Do not run both backends against the same publishing campaign. See [CrewAI AMP](https://docs.crewai.com/enterprise/introduction).

## Previously verified deployment facts (2026-09-23)

Read-only checks during this implementation found:

- `https://crewai.bun2too.com/health`: HTTP 200. Railway has this custom domain configured for CrewAI.
- `https://crewai.bun2too.com/ready`: HTTP 404. The currently deployed application does not expose the new readiness endpoint; the new application must be deployed.
- `https://n8n.bun2too.com/healthz`: HTTP 200.
- Railway's production CrewAI deployment-variable lookup reported no configured `MARKETING_API_KEY`, `LLM_MODEL`, `OPENAI_API_KEY`, Facebook settings, `PUBLIC_API_BASE_URL` or `DD_API_KEY`.
- The n8n deployment-variable lookup reported no explicit `DB_TYPE`, `N8N_ENCRYPTION_KEY` or `WEBHOOK_URL`. This does not mean its internally generated encryption key is missing; preserve its existing data/configuration.
- Local env files contain some infrastructure, model and Datadog credentials. Local presence is not proof of validity and does not install those variables in Railway. The local marketing API key is empty; Facebook and n8n management credentials have not been supplied for activation.

No live publishing, workflow activation, infrastructure mutation or credential changes were performed as part of these checks. No commit or push is implied by this document.

## 1. Verify locally before committing

From the repository root, with dependencies installed:

```sh
.venv/bin/python scripts/verify_marketing.py --terraform
```

Verification for this working tree passed 69 Python tests, 5 Terraform mock-provider tests, Terraform validation/format checks, workflow JSON/YAML parsing and Bash syntax checks. The command below reruns the offline checks. If Terraform is not initialized, first use the existing [deployment guide](deployment.md) to initialize the configured backend/provider. The tests themselves do not apply anything or require a Facebook token.

The mock end-to-end test covers schedule deduplication, all nine role callbacks, approval, publication ID, public article, repeat-poll suppression and actual-field-only metrics. Additional tests cover simultaneous claims, restart recovery, timed publishing, content/hash rejection, source network restrictions and Datadog retries/redaction. This still needs a live n8n import/activation test against the installed version; Docker is not running in the inspected local environment.

For local interactive operation, set `MARKETING_API_KEY`, `LLM_MODEL` and its provider key in ignored `crewai_agents/.env`. Keep `PUBLISHING_ENABLED=false` for initial manual draft checks. Fill `crewai_agents/config/marketing.json`, then run:

```sh
.venv/bin/python crewai_agents/start.py
```

Open `http://localhost:8000/docs`, authorize with the marketing key and use `/campaigns` for a manual draft. Scheduled `/automation/tick` needs `MARKETING_AUTOMATION_ENABLED=true` and configured/enabled Facebook delivery. Unattended generation is rejected when publishing is disabled or destination settings are missing. Use `/campaigns` for deliberate draft-only tests. The local worker stores scheduled work in `crewai_agents/.data`; do not point local tests at the production database. LLM calls require a valid provider account and may incur costs.

## 2. Complete the business profile once

Edit the packaged `crewai_agents/config/marketing.json`:

- Fill the intended audience and approved business facts; describe the actual products/services and value proposition.
- Configure one to eight public HTTPS RSS/Atom technology feeds. Scheduled runs collect recent entries, retain publication dates, prefer source diversity and pass the bounded evidence to CrewAI for topic selection. `research_max_age_days` and `research_item_limit` bound freshness and prompt size. Optional `source_urls` remain available for evergreen background facts.
- Add brand rules and forbidden phrases for claims/offers that should never be published.
- Retain `approval_mode=automatic`, `timezone=America/Chicago`, window `08:00`–`22:30`, daily cadence and a maximum one publication attempt per day, as requested.

The Page handle `bun2too` is not a replacement for `FACEBOOK_PAGE_ID`. Obtain the numeric Page ID and authorized Page access token from the business's Meta account/app. Use a supported Graph API version explicitly; do not rely on an unversioned URL. Page publishing ordinarily requires `pages_manage_posts` and read permissions such as `pages_read_engagement`; confirm the current permissions/access approval for the app and target Page in [Meta's documentation](https://developers.facebook.com/docs/pages-api/posts/).

## 3. Configure runtime and deployment secrets

Use the [complete GitHub configuration checklist](deployment.md#complete-github-configuration-for-the-mvp), also included in [README.md](../README.md#complete-github-configuration-for-the-mvp). It contains every GitHub Variable/Secret, both complete runtime JSON objects, the n8n credential setup, matching-key rules and production/QA differences. No additional secret checklist is maintained here.

## 4. Preserve n8n before changing its runtime/storage

Follow the [architecture migration procedure](marketing-mvp-architecture.md#n8n-persistence-and-existing-instance-migration) before enabling `N8N_VOLUME_READY=true`. It provisions `/home/node/.n8n`; mounting it empty over the current container files can hide the current owner, workflows and credentials. Do not replace its existing encryption key with a new local value just because both variables have the same name.

After verified backup/restore, configure `N8N_RUNTIME_CONFIG` from the central checklist, preserving the existing encryption key.

The MVP uses persisted SQLite for n8n and CrewAI. Configuring `DB_TYPE=postgresdb` alone would not migrate the existing SQLite contents; database migration is a separate operation. After cutover, restart n8n and confirm the same owner and credential/workflow records are available.

## 5. Deploy and verify without guessing what ran

Review the local diff and Terraform plan before committing. Keep secrets and local state ignored. Deploy the reviewed revision through GitHub Actions on the intended branch with `operation=deploy`; do not rerun an old job expecting it to pick up uncommitted code.

The job now tests code, applies infra/runtime variables, uploads CrewAI, polls `/ready`, updates the n8n workflows and activates the schedule when configured. Readiness is a configuration/worker check, not a live LLM or Meta authorization test. Missing `MARKETING_API_KEY` yields 503, a wrong key 401, and an old app without `/ready` 404.

To perform the same read-only runtime check locally with exported variables:

```sh
export CREWAI_BASE_URL='https://crewai.bun2too.com'
python3 scripts/check_marketing_runtime.py
```

The environment must contain `MARKETING_API_KEY`; the script never prints it. Once runtime verification succeeds, install/update workflows locally if needed:

```sh
export N8N_BASE_URL='https://n8n.bun2too.com'
export DEPLOY_ENVIRONMENT='production'
export MARKETING_TIMEZONE='America/Chicago'
export N8N_ACTIVATE_WORKFLOWS='true'
python3 scripts/deploy_n8n.py
```

This is a real mutation: requires exported `N8N_API_KEY` and `N8N_MARKETING_CREDENTIAL_ID`, and can activate publishing. It is the same installer used by CI. Keep `N8N_ACTIVATE_WORKFLOWS=false` if importing for inspection first. Templates are not instantiated merely by deploying the n8n Docker image.

In n8n, expect `[production] Marketing daily operations` and `Bun2too marketing errors (production)`. Inspect the former's credentials, active/published state and execution history. The error workflow is referenced by the main workflow and does not need its own active schedule.

## 6. Inspect a real campaign and publication

These commands work in macOS zsh/bash with values exported in the current shell. They read state and do not publish:

```sh
curl --silent --show-error --fail \
  --header "Authorization: Bearer ${MARKETING_API_KEY:?Export MARKETING_API_KEY}" \
  'https://crewai.bun2too.com/ready'

curl --silent --show-error --fail \
  --header "Authorization: Bearer ${MARKETING_API_KEY:?Export MARKETING_API_KEY}" \
  'https://crewai.bun2too.com/automation/status'
```

Use the returned run ID in `/docs` to inspect `/runs/{run_id}` and `/runs/{run_id}/work`. Verify all role outputs, source snapshots, article, approved hash, target window and actual publication outcome. A scheduled tick returns immediately; generation can take minutes. Polling is expected. An HTTP 200 from `/automation/publish` can contain `blocked` entries, so inspect its body and run events.

The status and tick responses include `publish_after`, `publish_before`, `attempt`, `reason` and sanitized `error` details. `publish_after` is the stable daily randomized target inside the configured window, not necessarily 08:00. Before that target the publisher reports `not_due`; this is normal. A successful HTTP request alone is not evidence of generation or publication. The installed workflow now records each operation's result, then checks it: failed generation, held review, blocked/expired release, failed metrics and failed/uncertain publication make the n8n execution fail. Asynchronous generation failures become visible on the next bounded status check or through the independent watchdog. Empty publish polls still report today's campaign states.

After a real publication, verify the Page displays the exact approved message and article link. `published` requires a returned remote post ID; a draft or approved run is not evidence of a live post. Open the public article URL without authentication to confirm it is reachable from Facebook.

Public articles use the editorial `/insights` index and responsive `/articles/{run_id}` layout. Each approved scheduled article requests one 3:2 WebP hero from the configured OpenAI image model and stores it under `DATA_DIR/article-assets` on the existing persistent volume. The page supplies the image through `/articles/{run_id}/artwork.webp` and advertises it in Open Graph metadata so Facebook can build a rich link preview. Artwork prompts prohibit text, logos, trademarks, identifiable people and photorealistic faces. Image failure records a warning and uses the built-in abstract CSS hero; it never blocks factual content or posting. The direct single-prompt Image API matches the [official OpenAI image generation guidance](https://developers.openai.com/api/docs/guides/image-generation).

### Recover failed generation after fixing its cause

The October 1 production failure came from a model rejecting the hardcoded `temperature=0.3`. The application now omits temperature and uses the provider default. Deploy the updated CrewAI application **and** reinstall the updated n8n templates using the normal deployment pipeline. Reinstalling only workflows cannot fix a model request in the worker.

Scheduled ticks now recover eligible generation timeouts and temporary provider errors after a ten-minute backoff, with at most three generation attempts per daily run. They also recover the existing pre-fix timeout record once the new code is deployed and Facebook validation passes. Authentication/policy failures and any previous social send are never automatically retried. Recovery keeps the original release window; expired days are not replayed. After deployment, inspect `/automation/status` (`retried` is also returned by `/automation/tick`). To explicitly retry a failed scheduled generation whose release window is still open, use the authenticated `POST /runs/{run_id}/retry-generation` endpoint in `/docs` with this body:

```json
{"reviewer": "operator-name"}
```

It returns 202 and queues generation for the worker. It keeps the same run ID, schedule slot, release window, attempt counter and event journal while clearing incomplete task outputs and the failed artifact. Repeated/concurrent requests cannot queue it twice. It refuses expired windows, nonfailed generation and **any previous Facebook publication attempt**. When the window has closed, let the next daily campaign run. Never delete the database or retry a Facebook send to recover generation.

### October 2 timeout and Facebook credential fixes

The old October 1 response with `created: false` was a readback of that day's failed run, not a new model call. October 2 did create a new run, which failed when OpenAI timed out under the old 90-second request/180-second agent limits. Defaults are now 240 seconds per model request, 900 seconds per agent, no hidden SDK or agent retries, a 6,000-token completion cap, and low reasoning effort for GPT model generations 5 and later. Optional runtime overrides are `LLM_REQUEST_TIMEOUT_SECONDS`, `AGENT_MAX_EXECUTION_SECONDS`, `LLM_MAX_COMPLETION_TOKENS`, and `LLM_REASONING_EFFORT`. Other model families retain their reasoning defaults unless explicitly configured. Invalid budgets fail before a model request. Persisted run settings and timeout events expose the actual limits used.

The deployed Facebook secret was a user token with existing Page-management grants. The publisher now resolves an authorized user token to the **exact configured Page's** access token, verifies `/me` matches `FACEBOOK_PAGE_ID`, and checks that Page's own `/posts` read access. Direct Page tokens also work. Tokens stay in memory and are never returned by status endpoints. Validation is cached for five minutes and invalidated by a credential/configuration change. The broader `/feed` read endpoint includes other users' content and was rejected even while `/posts` and `/published_posts` succeeded; it is not used for the read-only validation. Publishing still uses `POST /{page_id}/feed`.

Use authenticated `GET /automation/delivery-check` for a read-only destination test. It returns the Page ID/name and completed checks, or an actionable provider error. `GET /automation/research-check` reports current item counts, source domains, newest publication time and bounded feed failures without exposing article text. CI calls both endpoints after Railway deploys and before installing the n8n schedules. The delivery check cannot prove write permission; only a successful real post can. Scheduled ticks validate delivery before consuming a daily slot, and the worker rechecks before model spending. Invalid or revoked Meta access therefore fails promptly instead of generating content that has no usable destination.

The next metrics collection should record actual available counts and observation time. Check a later run's model context/deliverables for measured retrospective findings and a new hypothesis. A missing metric is not zero, and engagement is not proof of revenue.

## 7. Datadog and emergency operations

In Datadog Logs search `service:bun2too-marketing-api env:production`, then the run ID. Deployment logs use `service:bun2too-deployment`; n8n execution records use the same app service with `@kind:n8n_execution_failed`/`completed`. For agent/model spans use LLM Observability, app `bun2too-marketing-crew-team`, matching run/session ID. The production configuration must actually include the keys/flags; markdown instructions alone do not transmit logs.

Operational log `status` now contains a Datadog severity (`info`, `warning`, `error`); business states live in `outcome`. Successful schedule polls are informational. Root-cause records retain `operation`, `model`, `agent`, `attempt`, `campaign_key`, `duration_ms`, and sanitized `error.message`, `error.kind`, `error.stack`, and `error.causes` (including provider HTTP status, error code, parameter and request ID when available). Stack diagnostics contain frame locations without local variables or source lines. Prompt, artifact, tool-input and raw request/response fields are excluded. Publication failures retain Meta error details when available, including its trace ID. Events use their original timestamp even when export is retried.

n8n records carry `execution_id`, workflow/node/operation and business outcomes. `n8n_campaign_observed` records attach that execution to the actual campaign `run_id`, error and release window. Error-handler records also include the execution link and sanitized node error. Active Datadog spans contribute `dd.trace_id`/`dd.span_id`; worker failures retain the workflow trace correlation after unwinding. These IDs appear only when a real active span exists. Logging does not create Datadog monitors or change existing severity-remapping pipelines: if an informational completion still appears Critical, inspect that pipeline's status remapper.

Useful filters after deploying:

```text
service:bun2too-marketing-api env:production status:error
service:bun2too-marketing-api @kind:run_failed
service:bun2too-marketing-api @run_id:<campaign-run-id>
service:bun2too-marketing-api @execution_id:516
```

Old exported events are not rewritten or reclassified. Use fresh executions to verify the new fields, and `/observability/status` to verify intake acceptance and pending export count.

Confirm a recent `task_completed`, `facebook_publish_finished`, n8n execution event and deployment outcome in intake. The exporter omits prompt content from operational logs; LLM span capture is separate and optional. No infrastructure CPU/memory integration or alert monitor is installed by this change.

To stop publication immediately, set CrewAI `PUBLISHING_ENABLED=false` and ensure that variable change reaches the running deployment; also deactivate the main n8n workflow. Disabling the workflow alone will not revoke a request already executing. Never delete the publication database to clear an error.

For `publication_unknown` or a stuck `publishing`/`sending` record, inspect Facebook first. If the post exists, use `/social-publications/{id}/reconcile` with its numeric `PAGE_POST` ID and reviewer. The endpoint verifies Page and exact text. Do not resend blindly after a timeout. For auth failures renew the correct Page token; for policy blockers revise evidence/rules and regenerate. Retain failed runs for diagnosis.

## Live activation checklist

1. Confirm the deployed profile contains the approved business facts, audience and source feeds. The committed profile is populated; that does not establish which profile a deployment loads.
2. Numeric Facebook Page ID, supported API version and authorized Page token.
3. A populated shared marketing API key, installed consistently in CrewAI, GitHub and n8n.
4. n8n management API key and saved Header Auth credential ID.
5. Verified preservation/migration of the current n8n data and encryption key before attaching its volume.

Verify these prerequisites in the selected environment; this checklist does not assert they are currently missing. Repository changes and offline tests cannot establish live automatic operation.

The daily content contract supplies reviewers with the actual article URL, verified Page identity, automatic release policy and persisted window. Reviewers still require factual evidence and safe copy; they do not require an already-public draft, prior publication, infrastructure tickets, analytics instrumentation or an additional human signoff under automatic policy. All nine roles still run. The packaged profile gathers recent entries from GitHub Changelog, Cloudflare Blog and AWS News feeds; CrewAI selects a timely topic and cites only retrieved entry URLs.

Facebook can allow Page-owned post access while denying comments and reactions without `pages_read_user_content`. Metrics are now fetched independently: permitted counts are retained, unavailable counts have explicit `missing_metrics` diagnostics, and missing values are never recorded as zero. Partial collection produces a warning and `status: partial`; complete request failure remains an error. Add the missing Meta permission and reauthorize the configured token to collect those counters. This does not block posting.
