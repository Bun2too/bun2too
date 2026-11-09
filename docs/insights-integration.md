# Bun2Too Insights integration

## Ownership and routes

CrewAI remains the editorial/publishing backend. The main Next.js website at `/Users/beball/Development/bun2too/bun2too-website` now renders `/insights` and `/insights/[id]` inside its existing navigation/footer. Server-side requests use `INSIGHTS_API_ORIGIN` (default `https://crewai.bun2too.com`); there is no marketing/admin credential in the browser. The list revalidates every 60 seconds. Public article projections include only approved runs whose status is `published`, never prompts, reviewers, traces, errors or draft artifacts. Individual lookups remain available for articles older than the 100-item index/feed.

The legacy CrewAI `/insights` and `/articles/{id}` pages stay available with shared branding and canonical links to the main website. `INSIGHTS_SITE_URL` sets that main origin (default `https://bun2too.com`). Original artwork continues to load from the CrewAI service. The provided logo artwork is served from an explicit three-file allowlist.

Main-site rewrites proxy `/insights/feed.xml`, `/insights/feed.atom`, `/insights/unsubscribe`, and `/api/insights/push-*` to the corresponding public CrewAI routes. Nothing proxies `/runs` or `/automation`. Set the upstream at build time because Next.js rewrites are build configuration. The main site's `/articles` landing page and its article links lead to `/insights`.

## Shared signup and consent

The main-site insights pages reuse the existing `Newsletter` component and `/api/subscriptions` endpoint. AI & automation is preselected for insight digests, but email consent is unchecked. Existing Auth0 passwordless `email` connection behavior is retained: anonymous signup creates an unverified record in `pending_verification`; it does not create a password or activate delivery. Users sign in, verify their email and confirm preferences through `/account`. Anonymous requests cannot change an existing user's preferences.

The legacy insights pages embed `/insights/signup` from the main site so the same origin checks, Turnstile verification, consent validation and Auth0 server integration remain authoritative. Only this signup route permits framing by the main/insights/CrewAI origins; the rest of the site remains protected by `frame-ancestors 'none'`. Register production hosts in Turnstile and Auth0. Localhost signup configuration does not establish production readiness. Auth0 tenant/dashboard settings were not changed by this implementation.

## Email digest through Amazon SES

Selected sender: `info@bun2too.com`; SES region: `us-west-2` (Oregon). These are configuration choices, not evidence that the SES identity is verified.

Configure the following in the CrewAI GitHub `MARKETING_RUNTIME_CONFIG` secret, then redeploy:

- `AUTH0_DOMAIN`, `AUTH0_MANAGEMENT_CLIENT_ID`, `AUTH0_MANAGEMENT_CLIENT_SECRET`: a server-side Management API client with `read:users` and `update:users_app_metadata` (for unsubscribe). Use the same tenant/metadata namespace as the website. The website retains its own Management client for provisioning.
- `AWS_REGION`, `INSIGHTS_EMAIL_FROM`: SES region and a verified sender identity. Configure a scoped IAM role or AWS SDK credentials allowing `ses:SendEmail` for that identity. Railway does not inherit local `.aws` profiles. SES sandbox accounts can only send to verified recipients; request production access before enrolling the public.
- `INSIGHTS_UNSUBSCRIBE_SECRET`: at least 32 random characters, retained across deployments. Rotation invalidates existing email unsubscribe links; account preferences remain available.
- `INSIGHTS_DIGEST_ENABLED=true` only after delivery verification.

A separate notification worker (not an n8n schedule or the operations watchdog) scans for a weekly digest on Sundays after 09:00 America/Chicago, once per hour while due. It includes published articles from the last seven days. Search discovers candidate subscribers, then a direct Auth0 user lookup rechecks verified email, `newsletter.status=subscribed` and `ai-automation` topic before every recipient. Auth0 search is eventually consistent; new subscriptions may appear on a later scan. Search audiences of 1,000 or more fail explicitly instead of silently truncating; use an export-based audience before that scale.

Digest claims are keyed by week and normalized-email hash in mounted SQLite. No raw subscriber address is stored in that ledger. SES SDK automatic retries are disabled: a timeout or other send exception is marked `unknown` and raises an operational incident rather than risking a duplicate email. Claims left `sending` by a process crash also require reconciliation before replay. Review SES events before any manual ledger repair. This favors avoiding duplicates over automatic delivery recovery. SES acceptance is not inbox-delivery evidence. Configure SES bounce/complaint handling and suppression monitoring before a public launch.

Each digest has a signed unsubscribe link and RFC 8058 List-Unsubscribe headers. GET displays confirmation without changing preferences; POST updates Auth0 newsletter status. Unsubscribe applies to the existing newsletter preference, not just a second hidden digest list. The email also links to `/account` for topic management.

## On-site updates and browser push

The reading-list badge and unread list work without an account; read state is stored only in that browser's localStorage and does not sync across devices. There is no continuous browser polling. RSS and Atom work without signup.

Web Push is off until `INSIGHTS_PUSH_ENABLED=true` and `INSIGHTS_VAPID_PUBLIC_KEY`, `INSIGHTS_VAPID_PRIVATE_KEY`, `INSIGHTS_VAPID_SUBJECT` are set. Supply a matching P-256 VAPID key pair; use a `mailto:` contact for the subject. The private key stays server-side. The main site's root-scoped `/insights-sw.js` has push/click handlers only and does not intercept or cache website traffic. Permission is requested only after the visitor clicks Enable. UI reports unavailable/denied/unsupported states honestly. Turning notifications off unsubscribes the browser; expired server registrations are removed on a 404/410 push response.

Registrations require consent, a permitted Origin, bounded request size, known browser push-service hosts, correctly sized encryption keys, a per-client rate limit and a capacity limit. Do not replace the host allowlist with arbitrary URLs. Reverse-proxy deployments may share the observed client address and therefore the registration rate limit; verify forwarding before increasing registration volume. Push subscription endpoints are capabilities: restrict SQLite backups and access.

The notification worker checks for new published articles every 60 seconds locally. It sends only articles published after registration and within the last day. Delivery claims deduplicate per article/browser endpoint. Unknown send outcomes are recorded and alerted, not replayed automatically. It does not replay old articles to new subscribers. This adds no recurring n8n workflow executions.

## Rollout and verification

1. Deploy CrewAI with public API/feed/assets changes, keeping notification flags off. Verify drafts cannot be fetched through the new API/feed.
2. Deploy the main website with the new pages, rewrites and signup route. Confirm `/insights`, an older article, feeds and the embedded signup. Both repos contain pre-existing uncommitted changes; review them before committing.
3. Verify Auth0 passwordless signup and account confirmation in the production tenant using an authorized test address. Confirm the metadata is subscribed and email verified.
4. Configure SES identity/IAM and VAPID. Verify one controlled recipient/browser before enabling public delivery. No production email or browser push was sent during implementation.
5. Observe the authenticated `/automation/insights/status` delivery summary and existing operational incidents. Compare SES acceptance with actual inbox delivery. Keep mounted state across redeployments.

Local tests cover publication filtering, XML escaping, push-origin/SSRF checks, unsubscribe signatures, consent rechecks and duplicate-send claims. Browser checks use synthetic fixture articles and mocked signup responses; they do not prove live Auth0, SES, or push-provider authorization.
