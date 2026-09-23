# Production and QA deployment

Both environments live in the existing Railway project. A push to `main` selects GitHub environment `production` and HCP workspace `bun2too-production`. A push to `qa` selects GitHub environment `qa` and HCP workspace `bun2too-qa`. Other branches do not deploy.

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
5. Set runtime application credentials in **each Railway environment's CrewAI service**, including `MARKETING_API_KEY`, model/provider settings and any n8n handoff settings. GitHub environment secrets are not automatically application runtime variables. Keep QA social publishing disabled unless deliberately configured for test accounts.
6. Configure n8n/database connections separately if using them. This change initializes Postgres; it does not migrate n8n to Postgres or automatically wire application clients to it.

Production Terraform owns the shared project/service definitions. QA Terraform owns only the QA Postgres variables; it cannot create, delete or update shared services. A production change to a shared Railway service can affect both instances, because the provider can redeploy all instances. The workflow serializes both branches' deployments within the repository.

## GitHub environments and values

Create **Settings → Environments → production** and **qa**. Under deployment branches/tags, allow only `main` for production and only `qa` for QA. Add any production reviewers you require. These restrictions are GitHub settings; a YAML environment declaration alone does not configure them.

Add the following values to **each environment**, not to the local `.env` file:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `RAILWAY_API_TOKEN` | Account/workspace API token with access to this Railway project |
| Secret | `POSTGRES_PASSWORD` | That environment's database password; different for QA and production |
| Secret | `TF_API_TOKEN` | HCP Terraform team token (or permitted user token) with workspace read access, state read/write, and locking permissions |
| Variable | `TF_CLOUD_ORGANIZATION` | Your HCP Terraform organization name |
| Variable | `RAILWAY_PROJECT_ID` | `f5a4899e-a958-4353-b6a3-99a57b80ebad` in both environments |
| Variable | `RAILWAY_ENVIRONMENT_ID` | Production ID above, or the QA environment ID |
| Variable | `POSTGRES_SERVICE_ID` | Postgres service ID; production ID above |
| Variable | `CREWAI_SERVICE_ID` | CrewAI service ID from Railway |
| Optional variable | `POSTGRES_USER` | Default `postgres` |
| Optional variable | `POSTGRES_DB` | Default `bun2too` |

Services commonly retain the same service ID across environments in a single project. Environment IDs must differ. The preflight checks that the selected Railway environment name matches the branch and that both service IDs belong to the project. Store environment-specific credentials at environment scope rather than relying on repository-secret fallbacks.

No Railway credential values are printed. Terraform receives its account token as `RAILWAY_TOKEN`, while the CLI receives it as `RAILWAY_API_TOKEN`.

## Pipeline API calls and preflight diagnostics

The preflight makes exactly two requests, in order, stopping at the first failure:

1. `GET https://app.terraform.io/api/v2/organizations/{TF_CLOUD_ORGANIZATION}/workspaces/{TF_WORKSPACE}` with `Authorization: Bearer $TF_API_TOKEN`. For production this is `https://app.terraform.io/api/v2/organizations/Bun2tooinc/workspaces/bun2too-production`. It requires `data.attributes.execution-mode` to be `local`.
2. `POST https://backboard.railway.com/graphql/v2` with `Authorization: Bearer $RAILWAY_API_TOKEN` and `Content-Type: application/json`. The exact body for the configured project is:

   ```json
   {
     "query": "query($id: String!) { project(id: $id) { environments { edges { node { id name } } } services { edges { node { id } } } } }",
     "variables": {"id": "f5a4899e-a958-4353-b6a3-99a57b80ebad"}
   }
   ```

HTTP success alone is insufficient: Railway must return a project with no GraphQL errors, the selected environment ID must have exactly the name `production` or `qa`, and both distinct service IDs must belong to that project. Before either request, the script checks branch/environment/workspace mapping and required nonempty inputs. `POSTGRES_PASSWORD` is only checked for presence during preflight; it is not sent to either API.

The HCP workspace GET does **not** require an organization token. A team token can access workspaces granted to its team; a user token inherits the user's permissions, subject to organization policy. Use a team token with access to the selected workspace and state read/write plus locking permissions for this Local execution workflow. An organization token succeeding where a team token failed does not establish that the endpoint requires an organization token. Organization tokens are intended for administrative setup, and cannot start remote runs or create configuration versions. See [HCP token types](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/api-tokens) and [workspace permissions](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/permissions/workspace).

Railway must use an account/workspace token here. Project tokens use a different header (`Project-Access-Token`) and are not supported by this script's bearer authentication. See [Railway API authentication](https://docs.railway.com/integrations/api).

Later pipeline operations are separate from these two checks:

| Step | External access |
| --- | --- |
| Terraform setup/init | Installs Terraform/provider packages; the same `TF_API_TOKEN` is installed as Terraform's HCP credential for workspace/state access. |
| Terraform state list/apply | HCP state reads, locking, writes/unlocking; Railway provider reads and mutations for resources in `terraform/main.tf`, authenticated with the same Railway secret mapped to the provider's `RAILWAY_TOKEN`. Exact calls depend on the plan and provider implementation. Production must already have imported/migrated shared resources in state. |
| Postgres verification | Railway GraphQL `variablesForServiceDeployment(projectId, environmentId, serviceId)` reads the selected Postgres variables and compares the password locally without printing values. |
| Railway CLI deployment | `railway up --project … --service … --environment … --ci` uploads the checkout and starts/monitors the build using `RAILWAY_API_TOKEN`. |

The updated workflow logs `Deployment checkout: <commit>` and `Deployment diagnostics v2`, then a `Checking`/`Passed` line for each API check. Failures identify the operation and HTTP status, network/JSON failure, missing schema field, or failed validation without logging tokens or response bodies. If these markers are absent, the run is using an older workflow/script. Re-running an older GitHub Actions run uses its original revision; deploy a commit containing these changes on the intended branch.

To reproduce the exact production preflight locally, set `TF_API_TOKEN`, `RAILWAY_API_TOKEN`, and `POSTGRES_PASSWORD` to the same values as the GitHub **production environment** secrets, then run from the repository root:

```sh
GITHUB_REF_NAME=main \
DEPLOY_ENVIRONMENT=production \
TF_CLOUD_ORGANIZATION=Bun2tooinc \
TF_WORKSPACE=bun2too-production \
RAILWAY_PROJECT_ID=f5a4899e-a958-4353-b6a3-99a57b80ebad \
RAILWAY_ENVIRONMENT_ID=72e3af2d-37a3-430f-92ed-e0941b0b6435 \
POSTGRES_SERVICE_ID=dd68258c-7986-46e8-b8a7-e2830403ba17 \
CREWAI_SERVICE_ID=8eefe858-998d-4887-9f5c-bcacc5a16e3a \
python3 scripts/check_deployment.py
```

GitHub environment secrets override repository secrets with the same name. Updating a repository token alone may leave an older production environment token in use. A local pass also does not verify runner network access or subsequent Terraform write permissions.

## HCP Terraform and existing infrastructure

Create two CLI-driven workspaces in the same organization:

- `bun2too-production`
- `bun2too-qa`

Set **Execution Mode → Local** on both. GitHub Actions executes Terraform with that environment's credentials; HCP stores and locks state. The preflight checks the execution mode. Do not connect these workspaces to a second VCS-driven apply workflow. Limit access to state: it contains database passwords despite Terraform marking them sensitive.

The `cloud {}` configuration selects the organization via `TF_CLOUD_ORGANIZATION` and the workspace via `TF_WORKSPACE`. CI sets the workspace name from the branch. Local Terraform operations must set the same variables explicitly.

### One-time production state migration/import

The previous workflow used ephemeral local state. **Do not apply against an empty production HCP workspace:** it would create duplicate resources. CI now refuses to apply until all four existing shared resources are present in production state.

If you have the original state, back it up securely and run `terraform init` locally with `TF_WORKSPACE=bun2too-production` to follow HCP's migration prompts. The `moved` blocks preserve the original resource addresses when adding the production-only resource counts.

If the old runner's state is lost, import the existing resources into `bun2too-production`. From the repository root:

```sh
export TF_CLOUD_ORGANIZATION='YOUR_HCP_ORGANIZATION'
export TF_WORKSPACE='bun2too-production'
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

After HCP state setup, push the updated workflow to `main`, then merge it into `qa` and push that branch. The workflow verifies targets, applies the selected environment's Terraform, then uploads CrewAI to that Railway environment. `--ci` checks the application build; inspect Postgres runtime logs separately to confirm database health.

References: [HCP configuration/state migration](https://developer.hashicorp.com/terraform/cli/cloud/settings), [GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments), [Railway provider variable import](https://github.com/terraform-community-providers/terraform-provider-railway/blob/v0.6.2/docs/resources/variable.md).
