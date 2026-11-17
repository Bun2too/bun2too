---
name: railway-deployment
description: Prepare or diagnose this repository's Railway and n8n deployment while preserving environment identity and mounted state.
---

Read `docs/deployment.md`, `scripts/AGENTS.md` and `.github/workflows/deploy.yml`. Identify production versus QA and the requested operation. A full deploy requires successful verification and package publication; infrastructure-only/import-state deliberately skip publishing.

Use the existing scope, runtime configuration, credential, Terraform-state and n8n-volume checks. Saved plans and service variables contain secrets. Keep them local; never upload them as build artifacts. Preserve volumes, database identity and encryption keys.

Use `deploy_crewai.py` to wait for the exact deployment ID, then `check_marketing_runtime.py` before installing/enabling schedules. A healthy old service does not prove the uploaded build succeeded. Read back n8n activation and error-workflow linkage.

For access/platform errors, check current official Railway status and sanitized API errors; dated incidents do not establish current token validity. Avoid repeated deployment submissions during a provider queue incident. Do not rotate unrelated credentials or replace resources to work around a transient error. Report what is staged, deployed and verified separately.
