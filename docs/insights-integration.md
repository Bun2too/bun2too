# Bun2Too Insights integration

## Configuration reference

This is the canonical reference for the insights settings in this repository. The deployment checklist in `README.md` and `docs/deployment.md` points here; `crewai_agents/.env.example` uses the same names and defaults. Values below describe configuration, not verified live access.

### Where to configure each service

| Consumer | Local development | Hosted deployment |
| --- | --- | --- |
| CrewAI public pages and notification worker | Ignored `crewai_agents/.env` | Merge settings into GitHub **Settings → Environments → production (or qa) → Secrets → `MARKETING_RUNTIME_CONFIG`**. CI passes the JSON to Terraform, which writes the selected Railway service/environment variables. |
| Main Next.js website signup/account APIs | The website repository's ignored `.env.local` | Configure the website hosting environment. Auth0 Management and Turnstile secrets are server-only; public/build settings must be present when building the website. This CrewAI pipeline does not deploy website secrets. |

**Standalone GitHub secrets named `AUTH0_DOMAIN`, `AUTH0_MANAGEMENT_CLIENT_SECRET`, `AWS_REGION`, or `INSIGHTS_*` are not consumed by this workflow.** Put their values inside the complete `MARKETING_RUNTIME_CONFIG` JSON. Only `MARKETING_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY` have explicit standalone-to-runtime merging in `scripts/prepare_runtime_config.py`. Root `.env`, local AWS profiles, and the website's `.env.local` do not populate GitHub or Railway automatically.

All runtime JSON values must be strings, including `"true"` and `"false"`. Merge the insights entries into your existing map; do not replace the map and lose model, Facebook, telemetry or other settings. GitHub does not interpolate references to other secrets inside this JSON. Terraform state contains sensitive runtime values.

### CrewAI runtime settings

| Setting | Secret? | Value / source | Required for |
| --- | --- | --- | --- |
| `INSIGHTS_SITE_URL` | No | `https://bun2too.com`, without a trailing slash; use the corresponding main-site origin for QA | Canonical links, digest links, signup embed and permitted push registration origin |
| `INSIGHTS_DIGEST_ENABLED` | No | `false` initially; enable only after controlled delivery verification | Weekly SES digest worker |
| `AUTH0_DOMAIN` | No | `dev-bun2too.us.auth0.com` — tenant hostname only, **no `https://`, path or trailing slash** | Digest audience lookup and unsubscribe |
| `AUTH0_MANAGEMENT_CLIENT_ID` | Identifier | Client ID of an authorized server-side **Machine to Machine** application | Auth0 Management API access |
| `AUTH0_MANAGEMENT_CLIENT_SECRET` | **Yes** | Client secret belonging to that same Management application | Auth0 Management API access; never use a `NEXT_PUBLIC_` variable |
| `AWS_REGION` | No | Current checked-in configuration: `us-west-2` (Oregon). Verify the SES identity and IAM configuration in this exact region. | SES client region |
| `INSIGHTS_EMAIL_FROM` | No | `info@bun2too.com`; the sender identity/domain must be verified in the selected SES region | Digest From address |
| `AWS_ACCESS_KEY_ID` | Credential identifier | AWS SDK credential-chain input, when using explicit access keys instead of workload credentials | SES authentication, if no other supported credential source exists |
| `AWS_SECRET_ACCESS_KEY` | **Yes** | Matching scoped AWS secret key; use the same credential source as the access key ID | SES authentication with explicit keys |
| `AWS_SESSION_TOKEN` | **Yes** | Required only with temporary AWS credentials; omit for long-lived access keys. Temporary credentials also need a refresh mechanism. | Temporary AWS credentials |
| `INSIGHTS_UNSUBSCRIBE_SECRET` | **Yes** | At least 32 random characters, generated once and retained across deployments | Signing/validating unsubscribe links; separate from all API keys |
| `INSIGHTS_PUSH_ENABLED` | No | `false` initially; enable only after a controlled browser subscription/send check | Web Push worker and registration endpoint |
| `INSIGHTS_VAPID_PUBLIC_KEY` | No | URL-safe base64 public key from the generated VAPID P-256 key pair | Browser push subscription; intentionally exposed by `/insights/push-config` when enabled |
| `INSIGHTS_VAPID_PRIVATE_KEY` | **Yes** | Matching private key accepted by `pywebpush`; keep it server-side | Signing Web Push sends |
| `INSIGHTS_VAPID_SUBJECT` | No | `mailto:info@bun2too.com` | Contact identity in VAPID claims |

`PUBLIC_API_BASE_URL` remains the CrewAI origin, normally `https://crewai.bun2too.com`; it is different from `INSIGHTS_SITE_URL`. It supplies artwork URLs and existing publication links. Public articles and feeds do not require Auth0, AWS or VAPID credentials. Auth0 is needed for email consent/unsubscribe, not anonymous browser-push permission.

The previously discussed SES region was `us-east-2`; the current runtime default and `.env.example` are `us-west-2`. This reference follows the current repository configuration. Changing a region string does not migrate an SES identity or its verification.

### Auth0 application boundaries

The CrewAI Management client calls `https://<AUTH0_DOMAIN>/oauth/token` with audience `https://<AUTH0_DOMAIN>/api/v2/`. The worker derives that audience; it does **not** read `AUTH0_AUDIENCE` or `NEXT_PUBLIC_AUTH0_CLIENT_ID`.

Authorize its Machine to Machine application for `read:users` and `update:users_app_metadata` (unsubscribe). The main website may use a separate Management application in the **same tenant**, with additional provisioning permissions such as `create:users`. Do not substitute the browser SPA client ID/secret or an OpenAI/Railway token for Management credentials. Never expose the Management client secret to the browser.

| Main-website setting | Purpose | Used by this CrewAI worker? |
| --- | --- | --- |
| `AUTH0_DOMAIN`, `AUTH0_MANAGEMENT_CLIENT_ID`, `AUTH0_MANAGEMENT_CLIENT_SECRET` | Website server-side provisioning and preference updates; configure independently in the website host | Same names, independently configured values; same tenant, optionally separate clients |
| `AUTH0_AUDIENCE` | Audience of the website's authenticated preferences API | No; not the Management API audience |
| `AUTH0_EMAIL_CONNECTION` | Passwordless connection name, normally `email` | No; CrewAI reads existing user consent rather than provisioning users |
| `NEXT_PUBLIC_AUTH0_DOMAIN`, `NEXT_PUBLIC_AUTH0_CLIENT_ID`, `NEXT_PUBLIC_AUTH0_AUDIENCE`, `NEXT_PUBLIC_AUTH0_EMAIL_CONNECTION` | Public Auth0 React SDK configuration for the website SPA | No |
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | Public CAPTCHA widget key and server-only verification secret | No; signup remains on the main website |
| `INSIGHTS_API_ORIGIN` | CrewAI origin, normally `https://crewai.bun2too.com`; used by server fetches and build-time rewrites | No |
| `NEXT_PUBLIC_SITE_URL` | Main website origin, normally `https://bun2too.com`; keep aligned with `INSIGHTS_SITE_URL` | No |
| `INSIGHTS_EMBED_ORIGINS` | Main-site configuration for permitted signup-frame origins; follow the website repo's current format/defaults | No |

Digest delivery requires the Auth0 user to have `email_verified=true`, `app_metadata.bun2too.newsletter.status="subscribed"`, and `ai-automation` in the newsletter topics. Creating a passwordless record leaves consent pending; a successful signup response alone does not authorize email delivery.

### Runtime JSON merge example

Merge these entries into `MARKETING_RUNTIME_CONFIG`. Replace placeholders only for the features you configure; keep both delivery flags false until verified. Omit unused optional credential entries instead of deploying placeholder credentials. AWS credential keys are deliberately not included below: supply them securely through the SDK credential source chosen above.

```json
{
  "INSIGHTS_SITE_URL": "https://bun2too.com",
  "INSIGHTS_DIGEST_ENABLED": "false",
  "AUTH0_DOMAIN": "dev-bun2too.us.auth0.com",
  "AUTH0_MANAGEMENT_CLIENT_ID": "REPLACE_WITH_M2M_CLIENT_ID",
  "AUTH0_MANAGEMENT_CLIENT_SECRET": "REPLACE_WITH_M2M_CLIENT_SECRET",
  "AWS_REGION": "us-west-2",
  "INSIGHTS_EMAIL_FROM": "info@bun2too.com",
  "INSIGHTS_UNSUBSCRIBE_SECRET": "REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS",
  "INSIGHTS_PUSH_ENABLED": "false",
  "INSIGHTS_VAPID_PUBLIC_KEY": "REPLACE_WITH_VAPID_PUBLIC_KEY",
  "INSIGHTS_VAPID_PRIVATE_KEY": "REPLACE_WITH_MATCHING_VAPID_PRIVATE_KEY",
  "INSIGHTS_VAPID_SUBJECT": "mailto:info@bun2too.com"
}
```

### Verification and rotation

After deploying, authenticated `GET /automation/insights/status` reports feature flags, push registration count and delivery-state counts. It does not verify Auth0 permissions, SES identity/IAM, inbox receipt or VAPID validity. The CI provider-key read-back gate checks OpenAI/Anthropic/Gemini keys only; it does not validate these insights credentials.

Verify Auth0 lookup/preferences with a controlled test account, then SES acceptance and actual inbox receipt, and finally a controlled opt-in browser send. Keep delivery flags off until their prerequisites are ready. Rotate Management/AWS credentials in the runtime map and redeploy; update a separate website client only if that credential is shared. Retain the unsubscribe signing secret so existing links remain valid. Retain the VAPID key pair for existing subscriptions; replacing it requires a browser subscription migration, not just a new environment value. Do not automatically replay delivery rows marked `unknown` or left `sending` after a crash.

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
