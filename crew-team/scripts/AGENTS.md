# Automation context

Run helpers from the repository root. Most deployment scripts read explicit environment variables rather than loading every `.env` entry. Do not export entire configuration files into a shell or print secrets while diagnosing access.

- `verify_marketing.py`: offline Python and executable n8n regressions; disables external telemetry/workers.
- `publish_package.py`: validates `.github/package-targets.json` and publishes registered language packages. Containers use Docker Actions and digest read-back.
- `check_deployment_scope.py`, `check_deployment.py`: scope, credentials and target verification.
- `prepare_runtime_config.py`: secret runtime JSON for Terraform; output can contain credentials.
- `prepare_terraform_state.py`, `ensure_n8n_volume.py`, `check_n8n_storage_plan.py`: preserve existing resources and mounted data.
- `init_terraform.py`: at most three attempts for transient provider downloads; committed lockfile and signature/checksum verification remain mandatory.
- `apply_terraform.py`: bounded missing-CrewAI-source recovery; fresh upload, replan and storage guard before one retry. Infrastructure-only never uploads.
- `deploy_crewai.py`: upload once, then observe the exact deployment with at most ten checks one minute apart (600-second deadline). `--wait-for ID` observes only, without upload; a healthy older deployment is insufficient.
- `check_marketing_runtime.py`, `deploy_n8n.py`: validate runtime before enabling schedules; read back workflow activation.
- `marketing_batch.py`: operator-driven offline enrichment, not publication. Ambiguous submission must be reconciled before resubmission.

Keep production/QA identities explicit. Saved Terraform plans can contain secrets: do not publish them as build artifacts. Preserve `run_deployment_step.py` sanitized logging. Test integration logic with fakes; actual registry/provider success requires remote evidence.
