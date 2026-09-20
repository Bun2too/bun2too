# bun2too marketing agents

A FastAPI/CrewAI service for campaign planning, content creation and reviewed delivery to n8n. The API generates drafts; social platform actions run in separately configured n8n workflows.

## Credentials: where each one goes

| Credential/configuration | Local development | Railway deployment |
| --- | --- | --- |
| LLM provider key, e.g. `OPENAI_API_KEY` | `crewai_agents/.env` | CrewAI service Variables |
| `LLM_MODEL` | Same `.env`; example: `openai/gpt-4o` | CrewAI service Variables |
| `MARKETING_API_KEY` | Same `.env`; generate your own random secret | CrewAI service Variables |
| `N8N_WEBHOOK_URL`, `N8N_WEBHOOK_TOKEN` | Same `.env` | CrewAI service Variables |
| Facebook/Instagram/other social OAuth credentials and tokens | n8n **Credentials** | n8n **Credentials** |
| Social account/Page IDs, selected API version | n8n publishing workflow configuration | Same |
| n8n database connection and `N8N_ENCRYPTION_KEY` | n8n runtime environment | n8n service Variables; keep encryption key stable and backed up |
| `RAILWAY_TOKEN` for deployment | Not needed for generating campaigns | GitHub repository Settings → Secrets and variables → Actions |

CrewAI is the orchestration library; these local crews use your **LLM provider's key**. No CrewAI cloud API key is required for this path. CrewAI cloud tracing/deployment has its own optional account setup. A GitHub Actions secret does not automatically become a Railway service runtime variable.

Keep platform tokens out of agent prompts, source material and committed files. The example env file contains placeholders only. The API does not read Meta credentials because n8n owns the social integrations. It does not need an n8n management API key: `N8N_WEBHOOK_TOKEN` is your own shared secret for a Header Auth webhook.

For Meta, create the appropriate developer app and connect credentials in n8n. Page publishing needs authorization for the target Page; an app token alone is not sufficient. Check the current Page access-token and `pages_manage_posts`/`pages_read_engagement` requirements for your publishing endpoint, and obtain any required access approval. Other networks each require their own credentials and publishing workflow branch.

References: [n8n Facebook credentials](https://docs.n8n.io/integrations/builtin/credentials/facebookgraph/), [Meta's official Facebook API collection](https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api), [Meta Page posts](https://developers.facebook.com/docs/pages-api/posts/).

## Run locally

From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r crewai_agents/requirements.txt
cp crewai_agents/.env.example crewai_agents/.env
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Put the generated secret in `MARKETING_API_KEY`, choose `LLM_MODEL` and set the provider key in `.env`. Then:

```sh
uvicorn crewai_agents.app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs`, select **Authorize**, and enter your `MARKETING_API_KEY`. All business endpoints require bearer authentication; `/health` is public. Existing `/generate-post` clients must now send this header too. The model example is configurable; use a model available to your provider account. Non-default providers may need additional CrewAI dependencies.

## Marketing department

Edit `crewai_agents/app/agents.json` to change roles, goals and task prompts. The campaign crew runs in this order, with upstream deliverables supplied to later tasks:

| Agent | Deliverable |
| --- | --- |
| Product owner | Campaign charter, scope, prioritized backlog, budget assumptions |
| Business analyst | Audience hypotheses, requirements, acceptance criteria, attribution |
| Researcher | Supplied-source evidence and unsupported-claim flags |
| Creative | Concepts, design briefs, storyboards and image prompts |
| Writer | Social copy, calls to action and requested campaign copy |
| Engineering | Implementation tickets, tracking and automation specifications |
| Editor | Quality review, corrections and blockers |
| Delivery | Structured campaign package, final posts and proposed schedule |

Provide brand guidance, audience, source material and requested channels per campaign. Model, verbosity and tracing are environment settings; temperature, limits and workflow order are in `app/crews.py`. Restart/redeploy after configuration changes.

These agents create text deliverables. They do not browse, render images, execute engineering code, deploy sites, buy ads or fetch campaign performance. Add explicit tools and integrations for those operations as the department grows. Generated plans and metrics are proposals, not completed actions or observed results. No social credentials or publishing tools are given to the agents.

## Create, monitor, review and hand off

Use `/docs` to call `POST /campaigns` with:

```json
{
  "brief": "Plan a two-week bun2too awareness campaign. Propose a backlog and creative concepts; no paid spend is approved.",
  "audience": "Prospective customers; identify assumptions needing validation",
  "channels": ["facebook", "instagram"],
  "brand_guidelines": "Helpful, clear and factual. Do not invent testimonials or product claims.",
  "source_material": "Insert verified product information, dates and approved offers here."
}
```

1. The API returns `202` with a `run_id` and review URL. Generation continues in the service process.
2. Poll `GET /runs/{run_id}` for status, completed agent outputs and the final `artifact`. `GET /runs` lists the latest 100 runs. Artifacts include decision summaries, assumptions and risks; they are useful review evidence, not access to a model's private internal thoughts.
3. When status is `awaiting_review`, inspect every proposed post and campaign deliverable. Resolve blockers before approval. To regenerate, submit a new campaign with a revised brief and feedback.
4. Call `POST /runs/{run_id}/approve` with `{"reviewer":"your-name"}` to approve the saved artifact. To edit it first, include the complete revised `artifact` in the same body. Approval saves the reviewer label, timestamp and content hash. It requires an empty `blockers` list and only the requested channels. The original generated task outputs remain available.
5. Once n8n is configured, set `PUBLISHING_ENABLED=true` and call `POST /runs/{run_id}/dispatch`. This sends the exact approved artifact to n8n and may trigger publishing. Approval alone does not dispatch. An approved artifact is immutable through the API; create a new run for subsequent revisions.
6. `submitted` means n8n returned a successful HTTP response, **not that a post is live**. Inspect n8n Executions and the platform's post IDs/URLs to confirm publication. `dispatch_unknown` means reconcile n8n and platform results before a manual retry; automatic retries are deliberately disabled.

The shorter `POST /generate-post` endpoint accepts the original `article_text` and `topic_context` fields and returns `generated_post` plus `run_id`. It runs researcher → writer → editor → delivery synchronously and also saves an artifact for review. It never publishes by itself.

For debugging, `AGENT_VERBOSE=true` enables CrewAI console detail. Run/task completion is also logged with a run ID. `CREWAI_TRACING_ENABLED=true` opts into [CrewAI tracing](https://docs.crewai.com/en/observability/tracing), subject to its account setup; traces can contain campaign inputs and outputs. Standard API monitoring works without cloud tracing. [CrewAI agent configuration](https://docs.crewai.com/en/concepts/agents) documents execution controls and callbacks.

## Connect the n8n delivery workflow

No external workflow is created or activated by this repository. Configure one in your n8n instance:

1. Add a **Webhook** with method POST. Set **Header Auth**, header name `Authorization`, value `Bearer <N8N_WEBHOOK_TOKEN>`. Put its HTTPS production URL in `N8N_WEBHOOK_URL`; publish/activate the workflow when ready.
2. The request body contains `run_id`, `approval` and `artifact`. Validate it, restrict destination accounts to configured business accounts, and durably deduplicate by `run_id` (also sent as `Idempotency-Key`). That header alone does not make n8n idempotent. Track individual post indexes too so a partial campaign failure does not republish successful posts.
3. Read `artifact.posts`. Route each supported channel to its configured integration. Unsupported channels should fail visibly. Only publish the approved `text`; do not add another AI rewrite after approval. Treat `suggested_schedule` and `asset_brief` as proposals requiring explicit scheduling and asset preparation, not executable instructions.
4. For Facebook text publishing, use the Page feed endpoint with the approved message and authorized Page credentials. Instagram and media posts need additional asset creation/upload steps. Keep account IDs and tokens in workflow configuration/credentials, not model-generated destinations.
5. Save each platform's returned post ID/URL, run ID, timestamps and failures in a durable publication log. Use n8n **Executions** to inspect activity and an error workflow for alerts. Configure a suitable retention policy. Have n8n return an HTTP success only after the handoff is accepted; this API tracks submission, not downstream completion.

See [n8n webhook authentication, response options and execution inspection](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/).

## Deployment boundaries

This is a single-instance foundation. SQLite saves briefs, task outputs and approvals under `crewai_agents/.data` by default. On Railway, attach a persistent volume and set `DATA_DIR=/data`; otherwise redeployment can erase review history. Keep the API key with trusted operators: it grants generation, review and dispatch access, and the reviewer name is a supplied label, not an independently authenticated identity.

BackgroundTasks is not a durable job queue. A crash/redeploy can leave runs queued/running or dispatching with no worker. Inspect interrupted runs and submit a new generation if needed; reconcile dispatching runs with n8n before any retry. Before scaling to multiple replicas or unattended operation, move jobs and run storage to a durable worker queue and shared database, add authenticated reviewer identities, and implement publication-result reconciliation and measured campaign reporting.

The existing `terraform/main.tf` and deployment workflow remain scaffolding: database/n8n configuration and volumes are missing, and Terraform remote state is not configured. Deployment targeting and these infrastructure settings must be completed before calling this production-ready. Merely adding agents or a Railway token does not provision those connections.

Run local checks (LLM and n8n calls are mocked):

```sh
.venv/bin/python -m unittest discover -s crewai_agents/tests -v
```


### Terraform provider setup

The provider address is `terraform-community-providers/railway`, constrained to `~> 0.6.2`. Commit `terraform/.terraform.lock.hcl` to keep CI on the validated version. Service sources use `source_image` or `source_repo` with `source_repo_branch`; the CrewAI service root is `crewai_agents`.

CI supplies `TF_VAR_github_repository` from the GitHub repository running the workflow. For local Terraform planning, set it to your `owner/repository`. Terraform project creation needs a Railway account/workspace API token supplied as `RAILWAY_TOKEN`; a project-scoped token cannot create the parent project. The Railway GitHub integration also needs access to the source repository.

To initialize and validate without deploying:

```sh
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform validate
```

Provider documentation: [Railway provider](https://registry.terraform.io/providers/terraform-community-providers/railway/latest/docs).
