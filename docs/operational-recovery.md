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
WORKFLOW_HEARTBEAT_SECONDS=1200
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
- `POST /automation/recovery/resume` with `{"reviewer":"operator-name","run_id":"eligible-run-id"}`: after repairing billing/authentication, queue generation for that failed run and clear the durable pause. Omitting `run_id` clears only the pause, allowing future daily runs. Expired runs or runs with a prior social send cannot be regenerated.
- `POST /automation/notifications/{delivery_id}/retry` with `{"reviewer":"operator-name"}`: retry a blocked/exhausted alert after repairing its destination. Sent deliveries cannot be replayed with this endpoint.
- For unknown Facebook send outcomes, use the existing social-publication reconciliation endpoint after verifying the remote post. Do not regenerate or blindly retry the send.

A successful HTTP `/ready` response describes service readiness; it is not a live test of provider credits. A closed generation pause likewise does not prove billing has been restored—the next model request establishes that. Repeated permanent errors reopen the pause. Automatic transient retries stop after three generation attempts and at the persisted publishing deadline. An explicit operator retry can authorize another attempt; it is audited.

Notifications are **at least once**: a crash or transport timeout after remote acceptance can produce a duplicate alert. Stable incident/message IDs help identify duplicates. This delivery policy applies only to notifications, never Facebook publication. Incidents deduplicate repeated five-minute checks; reminders default to six hours. n8n fallback notices are throttled independently per workflow/node/channel for one hour and report their execution link without copying sensitive provider error bodies.

Missing n8n outcomes trigger heartbeat alerts after the configured grace period, including if schedules stop. n8n checks the independent watchdog and can notify directly if CrewAI is down. If both Railway/n8n and CrewAI are unavailable, neither can send; a separately hosted uptime/on-call monitor is still needed for that failure domain. This change does not provision an external monitoring account.

## Offline validation

```sh
.venv/bin/python scripts/verify_marketing.py
```

The verifier disables outbound alerting, LangSmith and publishing. Node.js enables execution of n8n Code-node regression tests. Live acceptance requires Slack API acceptance, SMTP sender/inbox confirmation, n8n workflow readback, and a successful generation after provider billing repair.

## Rollout and rollback

Deploy the CrewAI service before the updated n8n workflow, so the operational status endpoint exists when its new health check starts. Verify the exact Railway deployment reaches `SUCCESS`, `/ready` reports the worker ready, `/automation/operations/status` has a fresh heartbeat, and Slack delivery records contain accepted message IDs. Verify the n8n workflow's active state and error-workflow link after its update.

Keep the existing volume and database during any rollback. Do not delete incidents, publishing claims or the schedule slots to force a rerun. If the new service cannot start, restore the previous known-good deployment and investigate before resuming generation; reverting code does not repair provider billing. Persist the new notification configuration in the GitHub environment runtime secret as well as Railway before the next CI deployment. The n8n deploy step now forwards that runtime secret to its notification-credential provisioner.
