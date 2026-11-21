# Website glossary

These terms describe implemented website behavior. See [product context](docs/product.md), [architecture](docs/architecture.md) and the domain guides for contracts and configuration.

| Term | Meaning and boundary |
| --- | --- |
| Public website | Bun2too's service/content site; public pages render on the server. Service examples are not customer case studies. |
| CMS page / block | Contentful public path and ordered approved components. Copy/composition is editorial; rendering, authorization and consent controls stay in code. |
| Snapshot / fallback | Committed `src/content/website-seed.json`; deployment content, not an automatic backup of every CMS edit. |
| Insights | Local `/insights` views consuming the crew's public published-article API. Articles do not belong to the website CMS. |
| Account identity | Auth0-authenticated browser identity. OIDC login is separate from preferences API authorization and does not establish a Next.js server session. |
| Preferences access | Access token for the configured website API with `manage:subscriptions`; server validates issuer, audience, client, subject and expiry. |
| Pending subscription | Explicit anonymous email request awaiting verified identity and topic confirmation; not permission for campaign delivery. |
| Active subscription | Provider-verified email plus confirmed subscribed status/topics in Auth0. Account creation alone does not activate it. |
| Withdrawal | Authenticated newsletter unsubscribe or applicable signed digest unsubscribe; anonymous duplicates cannot reactivate it. Cookie withdrawal is separate. |
| Visitor support session | Signed HttpOnly `bun2too_support` cookie used for ownership/limits, independent of Auth0 identity; up to 24 hours. |
| Private inquiry | Explicitly consented contact form stored in private Netlify Blobs for 90 days. Does not enroll marketing, attach chats or automatically create a Relay case. |
| Saved reference | Evidence of confirmed inquiry persistence. Notification/acknowledgment acceptance does not establish inbox delivery. |
| Public AI answer | Optional single-question Open WebUI adapter with a fixed public-only model/collection and separate AI consent. Cannot mutate accounts or submit forms. |
| Availability / readiness | Session configuration/context flags. HTTP 200 or a true flag is not proof of storage, CAPTCHA, SMTP or model success. |
| Cookie preferences | Browser/origin-specific optional-storage choices; separate from newsletter, inquiry, AI, push and terms consent. |
| Component evaluation | Independent grading of each observed support-model call against versioned references. |
| Trajectory evaluation | Visible handler stages, guards, calls and outputs for a full tested workflow; does not expose hidden model reasoning. |
| Production human review | Approval of an exact release candidate/report. Structured scorecard is optional by default; actual approval is required. |

Use **inquiry** for the website form, **answer** for public AI output and **case** only for Relay's tracked domain. Runtime model/collection IDs, backend hosts and credentials are private configuration, never glossary facts.
