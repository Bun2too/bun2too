# CrewAI telemetry implementation and rollout

The application now has an enterprise OTLP/HTTP path alongside the legacy Datadog path. `TELEMETRY_ENABLED=true` selects OTLP. The launcher disables duplicate Datadog/CrewAI tracing in this mode. Application providers are private to this service, so CrewAI cannot replace them with its own global provider. OTLP traces and metrics use protobuf; the durable log journal uses OTLP JSON. Neither uses gRPC.

## Coverage implemented in this repository

| Area | Implementation |
|---|---|
| API | ASGI server spans, W3C inbound context, response `traceparent`/`X-Trace-ID`, normalized routes, request count/duration/status |
| Runs and jobs | Persisted request context; linked run traces with attempts and outcomes; full execution lifecycle including post-generation validation; durable progress/error events |
| Agent/task/model | Per-agent and per-task spans; pinned synchronous CrewAI native adapter instrumentation; actual usage, finish reason, latency, optional streaming TTFT/TPS, cost availability |
| Retrieval and policy | Source download and Atlassian reference spans; source count/age/failure metrics; credential egress input policy; existing output/publication policies traced |
| Integrations | HTTPX client instrumentation with safe URL export; Facebook publish outcomes; Atlassian actions; approval, n8n dispatch, artwork and engagement spans |
| Database | SQLite transaction spans inside run execution, without statements or parameters |
| Financial/business | Versioned model and image cost estimates; optional between-call run budget gate; engagement observations and missing-count metrics |
| Quality | Automatic deterministic citation/review/blocker measurements; authenticated ingestion of versioned external evaluations; cosine drift and rolling variance from supplied comparable embeddings |
| Replay | Authenticated opt-in download of existing redacted evidence; no automatic execution or publishing; access audit event |
| Export reliability | Independent locked export thread; journal retention on retryable failure; backoff/jitter/Retry-After; batch and request budgets; quarantine/requeue; full backlog count and age |
| Runtime/monitoring | Process memory/CPU/thread metrics, storage usage, worker readiness, queue depth, freshness and heartbeat gauges; Collector/Prometheus/Grafana configurations and alert rules |

Existing n8n callbacks retain their execution IDs and run associations. The API accepts W3C context when the caller supplies it. The bundled n8n workflows do not instrument n8n's internal engine or every node; platform tracing/log shipping is still needed for that coverage. A gateway should supply validated user identity for per-user attribution; the current API authenticates a shared service key and attributes resource ownership to a department.

No vector store exists in this application. Source retrieval is traced, but vector-query spans and MRR are not automatically invented. No extra evaluator model calls are made. Faithfulness/toxicity/ground-truth scores require a real evaluator or benchmark to submit them. The default credential check is not a complete prompt-injection or PII classifier.

## Local reference stack

From the repository root:

```sh
export GRAFANA_ADMIN_PASSWORD='choose-a-local-password'
docker compose -f observability/compose.yaml up -d
```

Set the following in the application environment, then start through `crewai_agents/start.py`:

```dotenv
TELEMETRY_ENABLED=true
OTEL_SDK_DISABLED=false
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
OTEL_SERVICE_NAME=bun2too-marketing-api
SERVICE_VERSION=your-release-or-commit
DEPLOYMENT_ENVIRONMENT=qa
TELEMETRY_DEPARTMENT=marketing
TELEMETRY_TRACE_SAMPLE_RATIO=1
```

Grafana is at `http://localhost:3000`, user `admin`; Prometheus is at `http://localhost:9090`. The “Crew — operations and AI observability” dashboard is provisioned automatically. Grafana Explore provides the Metrics, Traces, and Logs sources. Filter logs by service and `run_id`; use `trace_id` to open the corresponding trace. IDs remain metadata, not metric labels.

The Compose setup binds exposed ports to loopback. It is a development/reference stack, not a hardened production deployment. It uses pinned images, local disk, single replicas, and root in the storage-writing Collector/Tempo/Loki containers for volume initialization compatibility. Production must use approved image versions/digests, appropriately owned volumes and non-root identities, backups, TLS/authentication, access control, capacity planning and HA as needed. Do not expose its unauthenticated internal endpoints publicly.

## Production / Railway

1. Deploy an approved Collector with a persistent queue volume. The project does not create a Railway Collector service automatically.
2. Use `observability/collector.yaml` as a private-network starting point. Configure the trace/log backend endpoints; for an enterprise metrics backend, replace/add the Prometheus exporter with an approved OTLP/HTTP exporter. Configure authenticated TLS ingestion or place it behind the enterprise gateway. Install platform host/container metrics and approved log shipping separately.
3. Add the application settings above to `MARKETING_RUNTIME_CONFIG`; CI supplies `SERVICE_VERSION` from `GITHUB_SHA` unless explicitly set. Deployment preflight validates the OTLP transport and endpoint before contacting Railway. Use the Collector's HTTPS base URL. Supply `OTEL_EXPORTER_OTLP_HEADERS` in runtime secrets when the gateway requires authentication. Percent-encode header values, e.g. `Authorization=Bearer%20...`. Signal-specific `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `_METRICS_ENDPOINT`, and `_LOGS_ENDPOINT` override the base and must include the complete signal path.
4. Use `OTEL_ALLOW_INSECURE_HTTP=true` only for a deliberately trusted private network. Remote cleartext endpoints otherwise fail configuration validation. Keep `TELEMETRY_CAPTURE_CONTENT=false` and `REPLAY_EXPORT_ENABLED=false` unless content access is explicitly enabled under policy.
5. Load `observability/alerts.yaml` into Prometheus and configure Alertmanager routing to the service owner. The included rules evaluate alert state; they do not send notifications until a receiver is configured. Adjust the daily-publication and n8n thresholds for actual schedules.
6. Verify one test campaign, an induced failure, trace links, metrics, log arrival, a Collector outage/recovery, and an alert firing/resolving before switching production traffic.

Kafka/Event Hub is not required. If introduced, insert it between Collector tiers and define signal topics, retention, consumer lag monitoring, authentication, encoding and deduplication. Keep application OTLP/HTTP unchanged. Do not route the same event simultaneously through direct and queued paths without a deduplication plan.

## Pricing and budgets

Create a private rate card based on `config/model-pricing.example.json`, replace the placeholder model ID and every rate, then set `MODEL_PRICING_PATH` to its deployed path. Zero in the example is a placeholder, not a provider price. Text model keys must exactly match `LLM_MODEL`; the native request model is separately recorded on spans. Input, cached input and output rates are USD per million tokens.

For generated artwork, add an `images` object keyed by model and `size:quality`, with a USD estimate per generated image. The generator currently requests one image per call. Example structure, with your actual rates:

```json
{"version":"approved-rate-card-date","models":{},"images":{"exact-image-model":{"1536x1024:medium":0.0}}}
```

Missing rates or usage produce `unavailable` and a coverage metric. They never produce a fabricated zero cost. `RUN_COST_BUDGET_USD=0` disables the gate. A positive value checks accumulated run events before subsequent calls and blocks if prior cost is unknown or the budget has been reached. Configure provider spending limits as well: this is an observed-spend gate, not a preauthorization reservation or guaranteed dollar ceiling. Rates need to be available inside the container, not merely on the developer workstation.

## Quality and replay APIs

Authenticated `POST /runs/{run_id}/evaluations` accepts:

```json
{
  "evaluation_id":"benchmark-2026-10-04-run-001",
  "evaluator":"benchmark",
  "evaluator_version":"accuracy-v1",
  "dataset_version":"approved-fixtures-v1",
  "scores":{"faithfulness":0.92,"ground_truth_accuracy":0.9}
}
```

Allowed evaluators are `human`, `benchmark`, `model_judge`, and `embedding`. Allowed scores are `faithfulness`, `toxicity`, `context_relevance`, `mrr`, `ground_truth_accuracy`, and `useful_token_ratio`, between zero and one. An evaluation ID is idempotent and bound to a run. Version strings belong in event metadata; bounded evaluator/metric names are used in metrics.

For drift, submit a finite nonzero `embedding` plus `embedding_model`, evaluator version and dataset version. The first comparable sample establishes a normalized reference vector; subsequent samples record cosine distance and variance over the latest 100 distances. The cohort includes embedding model, dataset, prompt version and evaluator version. Use a fixed benchmark and version embedding models to avoid confusing topic shifts with model drift. No embedding is sent to the telemetry backend; the baseline vector lives in the restricted application database. Access and encryption policy must therefore cover that database too.

With `REPLAY_EXPORT_ENABLED=true`, authenticated `GET /runs/{run_id}/replay-bundle` downloads redacted brief, task plans, outputs, source snapshots and version metadata. It does not execute or publish anything. Responses are non-cacheable and exports are audited. Redaction and provider nondeterminism limit reproduction fidelity. Apply evidence-retention controls to downloaded files; never send them to ordinary logs.

## Export operations and recovery

`GET /observability/status` reports signal state, last log export, total pending records, oldest pending age and quarantine count. `pending_batch_count` remains the size of the next batch for backward compatibility; it is not total backlog.

Retryable failures leave events in SQLite. The independent exporter normally checks every two seconds and backs off on failure. Individual requests have a five-second timeout; a pass limits request count and elapsed work. Oversized individual records and permanent payload rejections are quarantined. Authentication failures retain the backlog so credentials can be corrected. Partial OTLP acceptance quarantines the batch because the receiver does not identify rejected event IDs.

Inspect the `telemetry_dead_letters` table on the restricted volume, fix the cause, then call authenticated `POST /observability/dead-letters/{event_id}/requeue`. A partial-acceptance requeue can duplicate previously accepted events; downstream deduplication uses the stable `(journal_id, event_id)` pair, which survives process restarts.

Collector persistent queues protect data after admission. SDK trace/metric buffers are in-memory and may lose their last unexported interval on abrupt termination. Metric counters are process-local and reset on restart. The durable event journal provides recovery evidence; it is not an exactly-once metrics ledger.

SQLite journal/artifact history is not automatically purged by this patch, because that history also drives campaign review and recovery. Establish an archival job and disk limits before sustained production use; never prune pending/quarantined rows. Tempo reference retention is seven days, Loki and Prometheus thirty days. Docker volumes are persistence, not backups.

## Verification and known deployment boundaries

Run `.venv/bin/python scripts/verify_marketing.py` with an installed Node runtime on PATH. Tests use fake provider responses and intercepted OTLP HTTP calls. They verify protobuf signal serialization, OTLP JSON correlation, context links, metadata handling, pricing, evaluation deduplication/drift, replay controls and export recovery without spending model tokens or publishing content.

Validation performed for this change: 163 offline regression tests passed; all observability YAML files parsed; Docker Compose configuration validation passed. The Collector metrics-reader configuration was checked against the pinned release source. Docker-based startup and end-to-end backend ingestion remain unverified because the local Docker daemon was not running. Parsing/configuration validation does not establish live ingestion. No production deployment, telemetry account configuration, external evaluator execution, notification delivery, per-user identity integration, or host-agent installation is performed by these source changes.
