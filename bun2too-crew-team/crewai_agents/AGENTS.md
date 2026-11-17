# Runtime context

`app/main.py` owns authenticated APIs and the durable worker. `app/store.py` owns SQLite run state and publication claims. `app/marketing.py` validates citations, editorial policy and the deterministic publishing contract. `app/crews.py` builds the team; `app/agents.json` defines manual-campaign roles/tasks.

Each role's persistent working knowledge is in `app/agent_context/<role>.md`, loaded into that agent's backstory. Keep these files short, role-specific and free of credentials, dated operational claims and unverified achievements. They complement task instructions; they do not replace current source snapshots or run-specific evidence. Docker copies this directory with the application.

Scheduled work uses its own prompts and dependencies in `crews.py`. Current intended sequence: product_owner → business_analyst → researcher → creative → writer → engineering → editor → tester → delivery. Tester reviews the edited candidate. Manual/social-only paths differ; preserve their behavior when changing scheduled work.

Current research snapshots are the citation allowlist. Recent publications are exclusions, not fresh evidence. Historical metrics must not inject old article/post copy into drafting context. Both Editor and Tester must approve; Delivery cannot override rejection. Publication policy, credentials, timestamps and external effects belong to deterministic application code.

Do not silently clear blockers, accept un-retrieved URLs, reopen expired windows, or retry ambiguous Facebook sends. Content revisions require fresh reviews and preserve rejection history. Provider retry classification differs from content rejection. See `docs/operational-recovery.md` and the `campaign-recovery` skill.

`start.py` configures observability before instrumented imports. OTLP, Datadog LLMObs and LangSmith have different configuration paths. Costs are estimates only when usage and a versioned rate card exist. Missing metrics are unknown, not zero.

`app/insights.py` projects published articles only for the main website and RSS/Atom. `app/insights_brand.py` skins legacy public pages. `app/insights_delivery.py` owns opt-in SES digests and browser push, using a separate worker and durable delivery claims. Auth0 remains the consent authority; anonymous signup is owned by the main site's existing API. Never send to pending/unverified/unsubscribed profiles or automatically replay ambiguous deliveries. See `docs/insights-integration.md` for deployment and credential prerequisites.
