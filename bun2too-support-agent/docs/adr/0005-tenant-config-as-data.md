# 0005: Tenant configuration is data

- Status: accepted
- Date: 2026-11-16

## Context

Relay is white-label. Per-brand code paths do not scale and leak one tenant's behaviour into another's.

## Decision

Everything brand-specific (branding, channels, enabled specialists, models, ticket field maps, policy thresholds) lives in `tenants/<slug>.yaml`, validated by `TenantConfig`. Source code never mentions a tenant slug; a structure test enforces this.

## Consequences

New behaviour needs a config field and a default. Onboarding a tenant is a config PR.
