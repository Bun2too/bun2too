---
name: package-publishing
description: Add or diagnose GitHub Packages publishing for this repository's container, npm, Maven, or Gradle builds.
---

Read `.github/package-targets.json`, `.github/workflows/publish-package.yml` and `docs/package-publishing.md` from the repository root. Register real build directories; do not create dummy packages or publish every discovered manifest.

Use `scripts/publish_package.py matrix` to validate targets. The current app publishes a container to GHCR. npm requires the lowercase `@bun2too` scope, explicit distributable files, a lockfile and a unique package version. Maven uses deploy-plugin 3.x destination overrides. Gradle requires its wrapper and `maven-publish` publications; the init script targets only GitHubPackages.

Keep `packages: write` on the publishing job, not the infrastructure job. Never publish runtime `.env`, Terraform state/plans, logs or databases. Preserve verify → publish → deploy ordering and infrastructure-only/import-state skips. Do not claim Railway runs the GHCR image: it currently builds the same source separately.

Run offline verification and workflow linting after changes. Registry acceptance is separate evidence: inspect the pushed container digest or the package version in GitHub Packages. Publication failure must fail the job. Check repository/package Actions access for a 403 before changing credentials or visibility. Existing user authorization controls whether to push or run a release.
