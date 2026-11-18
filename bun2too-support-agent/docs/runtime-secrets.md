# Runtime secrets (`SUPPORT_RUNTIME_SECRETS`)

Relay's runtime secrets reach Railway through one GitHub environment secret, `SUPPORT_RUNTIME_SECRETS`, set separately in `support-dev`, `support-qa` and `support-prod`. Its value is a JSON object whose keys are environment variable names and whose values are strings.

The deploy job passes it to Terraform as `TF_VAR_runtime_secrets` ([environment layer](../infra/terraform/railway/environment/main.tf)). Terraform splits it:

- `RELAY_TENANT_KEYS` goes to the **gateway** service.
- Every other key goes to the **agents** service.

Keys must be `UPPER_SNAKE_CASE`; Terraform rejects anything else. Never put these values in code, docs, issues, PRs or chat. Set them only through GitHub (`gh secret set … --env …` prompts for the value) and rotate them there.

## What each environment needs

`dev` runs with `RELAY_OFFLINE=1` (set by Terraform). Offline mode swaps the model and both ticket systems for deterministic stand-ins, so dev needs only the tenant keys. `qa` and `prod` run live: the agents service reads every key the tenant file names at start-up and fails to start if one is missing.

| Key                         | dev      | qa                 | prod     | Read by |
| --------------------------- | -------- | ------------------ | -------- | ------- |
| `RELAY_TENANT_KEYS`         | required | required           | required | gateway |
| `ANTHROPIC_API_KEY`         | not used | required           | required | agents  |
| `CF_AIG_ACCOUNT_ID`         | not used | required           | required | agents  |
| `CF_AIG_GATEWAY_ID`         | not used | required           | required | agents  |
| `CF_AIG_TOKEN`              | not used | required           | required | agents  |
| `BUN2TOO_JIRA_BASE_URL`     | not used | required (sandbox) | required | agents  |
| `BUN2TOO_JIRA_EMAIL`        | not used | required (sandbox) | required | agents  |
| `BUN2TOO_JIRA_API_TOKEN`    | not used | required (sandbox) | required | agents  |
| `BUN2TOO_SNOW_INSTANCE_URL` | not used | required (sandbox) | required | agents  |
| `BUN2TOO_SNOW_USER`         | not used | required (sandbox) | required | agents  |
| `BUN2TOO_SNOW_PASSWORD`     | not used | required (sandbox) | required | agents  |

**qa uses sandboxes.** The deploy runs the intake journey against qa, which creates real tickets. Point qa at a Jira sandbox project or site and a ServiceNow developer instance, never at production systems. The journey never runs against prod.

The `BUN2TOO_` prefix comes from the tenant. [`tenants/bun2too.yaml`](../tenants/bun2too.yaml) names the variables it reads (`base_url_env`, `email_env`, `token_env`, `instance_url_env`, `user_env`, `password_env`). A new tenant uses its own prefix, and its keys are added to this JSON the same way. To run a tenant without one of the systems, remove that system's block from the tenant file; then its keys are not needed.

## The keys

### `RELAY_TENANT_KEYS`

**What:** the API keys callers use to reach the gateway, and which tenant each key belongs to. Callers send a key as `x-api-key: <key>` or `Authorization: Bearer <key>`. The gateway looks it up and serves that tenant; an unknown key gets 401.

**Format:** comma-separated `key:tenant` pairs. The tenant is the file name in `tenants/` without `.yaml`.

```text
<key-for-website-widget>:bun2too,<key-for-smoke-tests>:bun2too
```

**How to get it:** you generate the keys yourself; nothing external issues them.

1. Generate one random key per caller, so each can be revoked alone. A key must not contain `:` or `,`.

   ```sh
   openssl rand -hex 32
   ```
2. Use different keys in each environment.
3. Give each caller its key through that caller's own secret store (for example, the website's Netlify environment). Never send it in chat or email.
4. To revoke a key, remove its pair and redeploy.

**`SMOKE_TENANT_KEY`** is a separate GitHub environment secret that the deploy's intake journey uses. It must be one of the keys in that environment's `RELAY_TENANT_KEYS`; give it its own pair, such as `<smoke-key>:bun2too`.

### `ANTHROPIC_API_KEY`

**What:** the Claude API key for the classifier and specialist agents. Models are chosen per tenant under `models:` in the tenant file.

**How to get it:**

1. Sign in at <https://console.anthropic.com> with the Bun2too organisation.
2. Create a workspace per environment (for example `relay-qa` and `relay-prod`), so spend limits and usage are separate.
3. In **API keys**, create a key in that workspace, named after the environment, and copy it once.
4. Set a monthly spend limit on the workspace.

### `CF_AIG_*` (Cloudflare AI Gateway)

**What:** model calls in qa and prod go through Cloudflare AI Gateway, which adds spend and usage analytics, rate limits, retries and provider fallback at Cloudflare's edge ([ADR 0007](adr/0007-cloudflare-ai-gateway.md)). Relay never lets the gateway store prompts or responses; only token, cost and latency metadata.

| Key | What | Example shape |
| --- | --- | --- |
| `CF_AIG_ACCOUNT_ID` | Your Cloudflare account ID | 32 hex characters |
| `CF_AIG_GATEWAY_ID` | The gateway's name in that account | `relay-qa`, `relay-prod` |
| `CF_AIG_TOKEN` | The gateway's authentication token | (secret) |

Leave all three out to call Anthropic directly (local development). Setting only one of the two IDs stops the agents service at start-up.

**How to get them:**

1. Sign in at <https://dash.cloudflare.com> with the Bun2too account. Copy the **Account ID** from the account home page (or **Account details**). This is `CF_AIG_ACCOUNT_ID`.
2. Go to **AI → AI Gateway → Create Gateway**. Name it `relay-qa` (one per environment: `relay-qa`, `relay-prod`). The name is `CF_AIG_GATEWAY_ID`.
3. In the gateway's **Settings**:
   - turn on **Authenticated Gateway**,
   - select **Create authentication token** and copy it once. This is `CF_AIG_TOKEN`.
   - Leave **Cache** off; support answers are personal.
   - Optionally set **Rate limiting** and a spend alert for the environment.
4. Leave the Anthropic key with Relay (`ANTHROPIC_API_KEY` above). The gateway forwards it; do not also store it in the gateway.
5. After the next deploy, open the gateway's **Analytics** and **Logs**: requests, tokens and cost should appear, and log entries should show no request or response bodies.

### `BUN2TOO_JIRA_*` (Jira Cloud)

Relay creates a Jira issue per escalated case, labels it with the case's correlation key, adds comments as the case progresses, and comments again when it resolves. It uses Jira Cloud REST v3 with basic authentication (email and API token).

| Key                      | What                                          | Example shape                  |
| ------------------------ | --------------------------------------------- | ------------------------------ |
| `BUN2TOO_JIRA_BASE_URL`  | Your Jira Cloud site, without a trailing path | `https://<site>.atlassian.net` |
| `BUN2TOO_JIRA_EMAIL`     | Email of the Atlassian account Relay acts as  | `relay-bot@<your-domain>`      |
| `BUN2TOO_JIRA_API_TOKEN` | API token for that account                    | (secret)                       |

**How to get them:**

1. **Account.** Create a dedicated Atlassian account for Relay rather than using a person's account, so tickets show who made them and access can be revoked alone. Invite it to the Jira site.
2. **Project.** Make sure the project in `tenants/bun2too.yaml` exists (`project: SUP`, issue type `Task`). Give the Relay account **Browse projects**, **Create issues** and **Add comments** in it (and **Transition issues** if `resolve_transition_id` is set).
3. **Priorities.** The project's priority scheme must contain `Highest`, `High`, `Medium` and `Low`, which Relay maps from sev1–sev4. Change `priority_map` in the tenant file if your names differ.
4. **Token.** Signed in as the Relay account, open <https://id.atlassian.com/manage-profile/security/api-tokens> → **Create API token**. Name it after the environment, set an expiry, and copy it once.
5. **Base URL.** The address you use to open Jira, up to `.atlassian.net`.
6. **qa.** Use a separate sandbox site, or at least a separate project with its own tenant file, so the deploy's intake journey never files tickets into the real queue.

### `BUN2TOO_SNOW_*` (ServiceNow)

Relay creates a record in the tenant's table (`incident` for Bun2too), finds it again by `correlation_id`, adds work notes, and closes it with `resolve_fields`. It uses the ServiceNow Table API with basic authentication.

| Key                         | What                                   | Example shape                        |
| --------------------------- | -------------------------------------- | ------------------------------------ |
| `BUN2TOO_SNOW_INSTANCE_URL` | Your instance, without a trailing path | `https://<instance>.service-now.com` |
| `BUN2TOO_SNOW_USER`         | User ID of the integration user        | `relay.integration`                  |
| `BUN2TOO_SNOW_PASSWORD`     | That user's password                   | (secret)                             |

**How to get them:**

1. **Instance.** For qa, request a free Personal Developer Instance at <https://developer.servicenow.com> (**Request Instance**). For prod, use the company instance and ask its ServiceNow admin for the steps below.
2. **User.** As an admin, open **User Administration → Users → New**. Create `relay.integration`, tick **Web service access only** so it cannot sign in to the UI, and save.
3. **Roles.** Give it a role that can create, read and update records in the table, for example `itil` for `incident`.
4. **Password.** On the user record, use **Set Password**, generate a strong one, and copy it once.
5. **Instance URL.** The address you open ServiceNow at, up to `.service-now.com`.
6. Developer instances go to sleep when unused and are reclaimed after a period of inactivity. Wake the qa instance before a qa deploy.

## Set the secret

Build the JSON locally, set it, and delete the file. The shapes below show which keys each environment needs.

```json
{ "RELAY_TENANT_KEYS": "<key>:bun2too,<smoke-key>:bun2too" }
```

```json
{
  "RELAY_TENANT_KEYS": "<key>:bun2too,<smoke-key>:bun2too",
  "ANTHROPIC_API_KEY": "<anthropic-key>",
  "CF_AIG_ACCOUNT_ID": "<cloudflare-account-id>",
  "CF_AIG_GATEWAY_ID": "relay-qa",
  "CF_AIG_TOKEN": "<gateway-token>",
  "BUN2TOO_JIRA_BASE_URL": "https://<site>.atlassian.net",
  "BUN2TOO_JIRA_EMAIL": "<relay-account-email>",
  "BUN2TOO_JIRA_API_TOKEN": "<jira-token>",
  "BUN2TOO_SNOW_INSTANCE_URL": "https://<instance>.service-now.com",
  "BUN2TOO_SNOW_USER": "relay.integration",
  "BUN2TOO_SNOW_PASSWORD": "<snow-password>"
}
```

The first is for dev, the second for qa and prod.

```sh
umask 077
$EDITOR /tmp/relay-dev.json                      # fill in the dev shape
jq empty /tmp/relay-dev.json && \
  gh secret set SUPPORT_RUNTIME_SECRETS -R Bun2too/bun2too --env support-dev < /tmp/relay-dev.json
gh secret set SMOKE_TENANT_KEY -R Bun2too/bun2too --env support-dev   # prompts; the <smoke-key> above
rm /tmp/relay-dev.json
```

Repeat for `support-qa` and `support-prod`. Changes take effect on the next deploy of that environment (Actions → `deploy-support` → **Run workflow**).

## Local development

`pnpm dev` defaults `RELAY_TENANT_KEYS` to `dev-bun2too-key:bun2too`. With `RELAY_OFFLINE=1` (as in `.env.example`) no other key is needed. To try real systems locally, unset `RELAY_OFFLINE` and set the same keys with sandbox values in `.env.local`, which git ignores.
