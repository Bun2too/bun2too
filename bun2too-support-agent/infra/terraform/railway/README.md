# Railway (POC): dev, qa, prod

Two Terraform root modules, with state in HCP Terraform:

| Layer          | Workspace                             | Owns                                                      | Applied by                                                       |
| -------------- | ------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------- |
| `project/`     | `bun2too-support-app`                 | Railway project, environments `dev` `qa` `prod`, services | `infra-support.yml` on merge, in the `infra-support` environment |
| `environment/` | `bun2too-support-dev`, `-qa`, `-prod` | Variables and secrets per service, the gateway's domain   | `deploy-support.yml`, inside each environment's deploy job       |

Volumes are created per environment by `scripts/deploy/ensure-volume.sh`, not by Terraform (see ADR 0004 in the root `docs/adr/`).

## First-time setup (a person, once)

1. Create the HCP Terraform workspaces above as CLI-driven workspaces. Set them to **local execution**, so runs happen in GitHub Actions and only state is stored. Give the environment workspaces read access to the project workspace's state (remote state sharing).
2. Create the GitHub environments `infra-support` (main only), `support-dev`, `support-qa` and `support-prod` with the secrets in `docs/sop/environments-and-release.md`. Add required reviewers to `support-prod`.
3. Run Actions → `infra-support` → apply. Then push any support-agent change, or run `deploy-support` for `dev`.

## Local checks (no credentials needed)

```sh
terraform -chdir=project init -backend=false && terraform -chdir=project validate && terraform -chdir=project test
terraform -chdir=environment init -backend=false && terraform -chdir=environment validate && terraform -chdir=environment test
```
