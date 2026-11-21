# Campaign recovery and notifications

The watchdog runs independently of campaign generation every 30 seconds when `OPERATIONS_ENABLED=true`. Enable alerts with `ALERTS_ENABLED=true`. Preserve the mounted SQLite volume: incidents, delivery attempts and the generation pause survive restart.

## Configuration

Set these in the CrewAI runtime secret map (`MARKETING_RUNTIME_CONFIG` for CI) and deploy:

```dotenv
OPERATIONS_ENABLED=true
ALERTS_ENABLED=true
ALERT_SLACK_BOT_TOKEN=<bot token>
ALERT_SLACK_CHANNEL=C0BTYU46YTB
ALERT_EMAIL_TO=bun2too@gmail.com
ALERT_EMAIL_FROM=<verified sender>
SMTP_HOST=<SMTP host>
SMTP_PORT=587
SMTP_USER=<SMTP user>
SMTP_PASSWORD=<SMTP password>
WORKFLOW_HEARTBEAT_ENABLED=true
WORKFLOW_HEARTBEAT_SECONDS=93600
STALLED_RUN_SECONDS=7200
ALERT_REMINDER_SECONDS=21600
```

SMTP uses verified TLS: STARTTLS on port 587, or implicit TLS on port 465. No sender is inferred from the recipient address. Missing sender configuration retains email deliveries as blocked; Slack can still work independently. SMTP acceptance does not prove inbox delivery; verify spam filtering and the sender's SPF/DKIM/DMARC configuration.

For independent n8n fallback alerts, pass the same notification variables to `scripts/deploy_n8n.py`, alongside its existing API key and workflow activation settings. The deployer stores Slack/SMTP secrets in encrypted n8n credentials; workflow JSON contains only credential references. If alert credentials are omitted, those fallback nodes are removed, so deploy with the complete operational configuration. The deployer does not read arbitrary secrets from the CrewAI service.

The Slack bot must belong to the intended workspace and be allowed to post to the selected channel. The supplied bot was verified as a member of `#fb-auto-workflow-notice` in the Bun2too workspace. No message-reading scope is required for delivery.

## Inspect and recover

All endpoints below require the marketing Bearer key. Do not paste it into tickets or alerts.

- `GET /automation/operations/status`: watchdog heartbeat, generation pause, open/resolved incidents, per-channel queue counts, recent delivery IDs, errors and accepted message IDs.
- `GET /runs/{run_id}/work`: detailed run journal and traces.
- `POST /automation/recovery/resume` with `{"reviewer":"operator-name","expected_circuit":{"run_id":"…","opened_at":"…","category":"provider_billing"},"run_id":"eligible-run-id"}`: after repairing billing/authentication, clear the durable pause you diagnosed and, if `run_id` is given, queue generation for that failed run. Copy `expected_circuit` from `generation_circuit` in `GET /automation/operations/status`. The server compares it with the open circuit and closes it in the same storage transaction. A different, newer or already-closed circuit, or a category other than `provider_billing`/`provider_authentication`, returns `409 {"detail":{"error":"circuit_mismatch","current":{…}|null}}` and changes nothing. An ineligible `run_id` (expired, or with a prior social send) also returns 409, and the circuit stays open. Omitting `run_id` clears only the pause, allowing future daily runs. Status reports `resume_contract: "compare-and-resume/v1"`; clients must not POST to a server that lacks it.
- `POST /automation/notifications/{delivery_id}/retry` with `{"reviewer":"operator-name"}`: retry a blocked/exhausted alert after repairing its destination. Sent deliveries cannot be replayed with this endpoint.
- For unknown Facebook send outcomes, use the existing social-publication reconciliation endpoint after verifying the remote post. Do not regenerate or blindly retry the send.

A successful HTTP `/ready` response describes service readiness; it is not a live test of provider credits. A closed generation pause likewise does not prove billing has been restored—the next model request establishes that. Repeated permanent errors reopen the pause. Automatic transient retries stop after three generation attempts and at the persisted publishing deadline. An explicit operator retry can authorize another attempt; it is audited.

Notifications are **at least once**: a crash or transport timeout after remote acceptance can produce a duplicate alert. Stable incident/message IDs help identify duplicates. This delivery policy applies only to notifications, never Facebook publication. Incidents deduplicate repeated watchdog observations; reminders default to six hours. n8n fallback notices are throttled independently per workflow/node/channel for one hour and report their execution link without copying sensitive provider error bodies.

Missing n8n outcomes trigger heartbeat alerts after the configured grace period, including if schedules stop. n8n checks the independent watchdog and can notify directly if CrewAI is down. If both Railway/n8n and CrewAI are unavailable, neither can send; a separately hosted uptime/on-call monitor is still needed for that failure domain. This change does not provision an external monitoring account.

## Manual GitHub inspection and billing resume

The existing deployment workflow also accepts manual `inspect-publishing` and `resume-publishing` operations, with an explicit `recovery_environment` of `production` or `qa`. These operations use only that environment's existing marketing/n8n API credentials. They run the recovery safeguard tests, then `scripts/recover_marketing.py`; they do not depend on Terraform, package publication or model evaluations. Existing environment branch protections still apply.

Run inspection first and confirm the live failure category. After restoring provider billing, run resume only for a confirmed `provider_billing` pause. Resume omits `run_id`, clears the pause for future daily slots, and reads back its state. It never queues expired work or sends a Facebook post. Other pause categories require separate diagnosis and their existing operator recovery path. An already closed circuit is left alone.

Reports contain selected status/error metadata and n8n activation, schedule and execution evidence; private drafts, provider bodies and credentials are withheld. A failed mutation is never retried automatically. Inspect state before retrying an ambiguous response. A successful resume means future generation is enabled, not that credits or publication have been verified. Observe the next campaign and confirm both the public article and Facebook publication.

## Offline validation

```sh
.venv/bin/python scripts/verify_marketing.py
```

The verifier disables outbound alerting, LangSmith and publishing. Node.js enables execution of n8n Code-node regression tests. Live acceptance requires Slack API acceptance, SMTP sender/inbox confirmation, n8n workflow readback, and a successful generation after provider billing repair.

## Rollout and rollback

Deploy the CrewAI service before the updated n8n workflow, so the operational status endpoint exists when its new health check starts. Verify the exact Railway deployment reaches `SUCCESS`, `/ready` reports the worker ready, `/automation/operations/status` has a fresh heartbeat, and Slack delivery records contain accepted message IDs. Verify the n8n workflow's active state and error-workflow link after its update.

Keep the existing volume and database during any rollback. Do not delete incidents, publishing claims or the schedule slots to force a rerun. If the new service cannot start, restore the previous known-good deployment and investigate before resuming generation; reverting code does not repair provider billing. Persist the new notification configuration in the GitHub environment runtime secret as well as Railway before the next CI deployment. The n8n deploy step now forwards that runtime secret to its notification-credential provisioner.

### Content rejection recovery

For a diagnosed source/editorial defect, deploy the correction first, then use authenticated `POST /runs/{run_id}/revise-content` with a reviewer identifier. This is separate from retrying provider failures. It preserves the rejected draft for audit, requires fresh generation and both content approvals, and refuses expired windows, three-attempt runs, or any existing publication attempt. See [October 22 RCA and recovery instructions](incident-2026-10-22.md). Never clear citation checks or reviewer rejection flags to force publication.


## Daily orchestration and bounded checks

The managed marketing workflow now starts generation once daily at **08:05 America/Chicago**, after the configured 08:00 campaign anchor. Keep this schedule aligned if the profile's anchor/timezone changes. Metrics still run once at 07:45. The independent `Marketing service health` workflow runs at 00:15, 06:15, 12:15 and 18:15. There are six scheduled starts daily instead of 865; error-handler executions occur only on failures.

After reserving the daily campaign, the marketing execution persists in a Wait node for 15 minutes, then reads that exact run. It checks at most six times (up to 90 minutes), using Wait nodes between checks rather than starting new workflows. The existing CrewAI watchdog owns transient generation retries (maximum three attempts); n8n does not create replacement campaigns. An approved run waits until its persisted `publish_after` timestamp, then publishes once. If generation finishes after that timestamp but before the deadline, it publishes as soon as approval is observed. Published runs finish without another send. Rejected, permanently failed, expired or unknown-publication states stop with the run ID. The per-day campaign slot, approval gates and publication claims remain in force.

Initial generation reservation and read-only status/health calls allow three HTTP attempts with five-second spacing on request failure. Facebook publication has no automatic HTTP retry. If the publication response is lost, inspect the existing publication claim and remote post before operator recovery. Successful waits do not count as retries or start additional executions. Waiting executions need persistent n8n storage and must not be deleted during redeployment; inspect active/waiting executions before manually starting another copy.

The daily generation heartbeat has a minimum 26-hour grace (93,600 seconds), even if a legacy 1,200-second environment value remains. Publication is conditional and no longer treated as an always-arriving heartbeat; the watchdog monitors campaign failures and publishing deadlines. Deploy the service change before installing the new workflows to avoid false missing-heartbeat alerts. On a generation wait exhaustion, fix the reported issue and explicitly resume/re-run within the valid publication window; do not regenerate expired content.

The internal watchdog still checks local state every 30 seconds and deduplicates notifications. The separate six-hour n8n health check is a low-frequency fallback, not continuous external uptime monitoring: a full CrewAI outage can take up to six hours to be detected by it. A dedicated external uptime monitor can provide faster outage alerts without filling marketing execution history, but none is provisioned by this change. Health failures retain the existing error workflow and configured Slack/email fallback paths.

The marketing workflow removes the old 660-second execution timeout to allow durable waits through the publishing window. Each HTTP operation retains its request timeout; status checks and publication deadlines bound business work. n8n supports persisted Wait nodes for this use ([Wait documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/)). Local JavaScript and deployment tests validate the branches; actual n8n pause/resume and notification delivery still require deployment verification.
