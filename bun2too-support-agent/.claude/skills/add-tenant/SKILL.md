---

name: add-tenant
description: Onboard a new white-label tenant to Relay from config alone. Use when asked to add a brand, demo customer, or new deployment of Relay.
---

# Add a tenant

1. Copy `tenants/_template.yaml` to `tenants/<slug>.yaml`. The slug is lowercase letters, digits and hyphens.
2. Fill brand, channels, specialists, models, ticket mappings and policy. Credentials are env var names only.
3. Run `uv run --directory services/agents pytest tests/test_tenants.py`: every tenant file must parse.
4. If the tenant needs behaviour no config field expresses, stop. Write a ticket for the config field instead of adding a code branch (ADR 0005).
5. Drive one intake for the new tenant with the `verify-relay` skill (`RELAY_TENANT_KEY=dev-<slug>-key`).
