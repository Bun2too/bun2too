# Railway (POC): dev, qa, prod

Two Terraform root modules, with state in four HCP Terraform workspaces, all in the HCP project `bun2too-support-app` (organization `Bun2tooinc`):

| Layer          | Workspace                             | Owns                                                      | Applied by                                                       |
| -------------- | ------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------- |
| `project/`     | `bun2too-support-project`             | Railway project, environments `dev` `qa` `prod`, services | `infra-support.yml` on merge, in the `infra-support` environment |
| `environment/` | `bun2too-support-dev`, `-qa`, `-prod` | Variables and secrets per service, the gateway's domain   | `deploy-support.yml`, inside each environment's deploy job       |

Volumes are created per environment by `scripts/deploy/ensure-volume.sh`, not by Terraform (see ADR 0004 in the root `docs/adr/`).

## First-time setup (a person, once)

1. In the HCP project `bun2too-support-app`, create the **four** workspaces above as CLI-driven workspaces: `bun2too-support-project`, `bun2too-support-dev`, `bun2too-support-qa` and `bun2too-support-prod`. The HCP project is only a folder; the project layer still needs its own workspace.
   - Set each workspace's Execution Mode to **Local** (Settings → General), not "Organization default". Runs happen in GitHub Actions with the job's inputs, and HCP stores only state. In Remote mode, `terraform apply` fails with "Failed to create configuration version".
   - On `bun2too-support-project`, share its state with the three environment workspaces (Settings → General → Remote state sharing).
   - Both workflows check all of this before `terraform init`. On a miss, they list the workspace names and execution modes the token can see.
2. Create the GitHub environments `infra-support` (main only), `support-dev`, `support-qa` and `support-prod` with the secrets in `docs/sop/environments-and-release.md`. Add required reviewers to `support-prod`.
3. Run Actions → `infra-support` → apply. Then push any support-agent change, or run `deploy-support` for `dev`.

## Local checks (no credentials needed)

```sh
terraform -chdir=project init -backend=false && terraform -chdir=project validate && terraform -chdir=project test
terraform -chdir=environment init -backend=false && terraform -chdir=environment validate && terraform -chdir=environment test
```
