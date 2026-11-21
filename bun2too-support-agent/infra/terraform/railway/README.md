# Railway (POC): dev, qa, prod

One Terraform module. Each environment is one name everywhere:

| Environment | Railway project (environment)   | HCP Terraform workspace | GitHub environment |
| ----------- | ------------------------------- | ----------------------- | ------------------ |
| dev         | `bun2too-support-dev` (`dev`)   | `bun2too-support-dev`   | `support-dev`      |
| qa          | `bun2too-support-qa` (`qa`)     | `bun2too-support-qa`    | `support-qa`       |
| prod        | `bun2too-support-prod` (`prod`) | `bun2too-support-prod`  | `support-prod`     |

The workspaces live in the HCP project `bun2too-support-app` (organization `Bun2tooinc`). Each state owns its environment's whole Railway project: the project, the services `gateway`, `agents` and `postgres`, their variables and secrets, and the gateway's domain. `deploy-support.yml` applies it in each environment's deploy job, before `railway up`.

Volumes are created per environment by `scripts/deploy/ensure-volume.sh`, not by Terraform (see ADR 0004 in the root `docs/adr/`).

## First-time setup (a person, once)

1. In HCP Terraform, set each of the three workspaces' Execution Mode to **Local** (Settings → General), not "Organization default". Runs happen in GitHub Actions with the job's inputs, and HCP stores only state. In Remote mode, `terraform apply` fails with "Failed to create configuration version". The deploy job checks this before `terraform init`, and on a miss lists the workspace names and execution modes the token can see.
2. Create the GitHub environments `support-dev`, `support-qa` and `support-prod` with the secrets in `docs/sop/environments-and-release.md`, and the repository variable `RAILWAY_WORKSPACE_ID`. Add required reviewers to `support-prod`.
3. Push any support-agent change, or run `deploy-support` for `dev`. The first apply creates that environment's Railway project.

## Local checks (no credentials needed)

```sh
terraform init -backend=false && terraform validate && terraform test
```
