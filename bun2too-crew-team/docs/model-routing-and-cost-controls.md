# Model routing and cost controls

The campaign uses explicit per-agent routes. Enable `MODEL_ROUTING_ENABLED=true`; unconfigured tiers retain `LLM_MODEL`. There is no automatic cross-provider fallback after an error, so billing outages cannot silently spend another provider's budget. The existing recovery circuit and alerts still apply.

| Work | Agents | Route | Default output cap |
| --- | --- | --- | --- |
| Routine planning/formatting | product_owner, business_analyst, creative | `LLM_ROUTINE_MODEL` | 2,500 |
| Artifact assembly | delivery | `LLM_ROUTINE_MODEL` | 6,000 (includes the full article) |
| Research, writing, technical checks, review | researcher, writer, engineering, tester, editor | `LLM_COMPLEX_MODEL` | 6,000 |

Caps never exceed the global `LLM_MAX_COMPLETION_TOKENS` unless explicitly overridden with `LLM_MAX_TOKENS_<ROLE>` (512–16,000). Each role can override the tier with `LLM_MODEL_<ROLE>`. OpenAI uses `max_completion_tokens`, Gemini uses `max_output_tokens`, and Claude uses `max_tokens`. Only compatible OpenAI model families receive reasoning-effort settings. Review and approval gates remain in effect regardless of model.

Example after configuring developer API keys:

```dotenv
MODEL_ROUTING_ENABLED=true
LLM_ROUTINE_MODEL=gemini/gemini-2.5-flash-lite
LLM_COMPLEX_MODEL=anthropic/claude-sonnet-4-6
LLM_MODEL_DELIVERY=openai/gpt-4.1-mini
GEMINI_API_KEY=<private developer key>
ANTHROPIC_API_KEY=<private developer key>
OPENAI_API_KEY=<private developer key>
ANTHROPIC_PROMPT_CACHE_ENABLED=true
RUN_MAX_LLM_CALLS=36
```

Use `openai/gpt-4.1-mini` for the routine tier while Gemini is unavailable. These are configurable baseline model IDs, not a claim that they are the newest or universally optimal. Benchmark approved content, rejection rate, latency and measured spend before changing models. Provider-native adapters are included in the pinned CrewAI dependency extras.

Claude caching marks stable system messages using CrewAI's native cache breakpoint support. Changing task data is not marked. Providers enforce minimum cacheable lengths and TTLs; short prompts may have no cache hit. Do not pad prompts merely to reach a cache threshold. Telemetry preserves cache-read and cache-write tokens. Rate cards must include `cache_creation_per_million` when cache writes occur; otherwise cost is reported unavailable rather than underestimated.

`model_route_selected` events record role, tier, provider, model and cap. `llm_call_finished` records the actual selected model and usage. `RUN_MAX_LLM_CALLS` stops subsequent model calls once the persisted run reaches its limit (including earlier attempts and recorded image calls). The existing `RUN_COST_BUDGET_USD` uses versioned rates from `MODEL_PRICING_PATH` and blocks subsequent calls when measured spend reaches the threshold or usage is unknown. It is a **between-call guard**, not a guaranteed dollar ceiling: a call can cross the threshold, and parallel runs/account activity are outside it. Output and call caps bound work, not total account billing.

Use separate provider projects/keys for this workload, small funded balances where supported, and provider-enforced spending limits. Budget alerts are not necessarily hard limits. Funding wallets or configuring account-level blocking requires account-owner access; this deployment does not create wallets, fund accounts, or claim to enforce a $10 account cap. Include images, cache writes, retries and batch jobs when reviewing total spend.

## Non-urgent batch processing

`scripts/marketing_batch.py` provides prepare/submit/poll/collect for OpenAI and Anthropic. It only accepts `tagging`, `enrichment` and `log_summary`; it never publishes Facebook posts or changes approval state. Current daily generation remains synchronous because its agents depend on earlier outputs and have a publication deadline. Batch results are offline review artifacts, not automatically fed into the publishing workflow.

```sh
umask 077
# inputs.json contains an array of reference-text strings, with credentials removed.
python scripts/marketing_batch.py prepare yesterday-tags --db /private/path/batches.sqlite \
  --provider openai --model gpt-4.1-mini --task tagging --input inputs.json --max-tokens 1000
python scripts/marketing_batch.py submit yesterday-tags --db /private/path/batches.sqlite
python scripts/marketing_batch.py poll yesterday-tags --db /private/path/batches.sqlite
python scripts/marketing_batch.py collect yesterday-tags --db /private/path/batches.sqlite --output results.json
```

Use `--provider anthropic --model claude-sonnet-4-6` for Claude. The queue persists intent before submission and prevents duplicate job keys and concurrent submissions. A timeout leaves `submission_unknown`; do not create a replacement batch until an operator reconciles the provider console. A crash in `submitting` needs the same reconciliation. Collection retains both successful results and per-item errors. The operator controls polling and must review failed/expired jobs; this CLI does not schedule batches or send their status through campaign alerts. Limits: 1,000 items, 50,000 characters per item, 128–4,000 output tokens per item. Batch spend is separate from the campaign run budget. Protect and retain/delete the SQLite database and result files according to your data policy.

Official references: [OpenAI Batch API](https://developers.openai.com/api/docs/guides/batch) and [Anthropic batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing) document discounted asynchronous processing; [Claude prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) describes cache thresholds and billing. [Gemini Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite) and [OpenAI Mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) document baseline models. Discounts and cache savings do not establish realized ROI for this campaign.

## Activation record — October 16, 2026

Production runs with routine OpenAI Mini routing enabled; complex agents retain the existing `LLM_MODEL`. Gemini and Claude keys were unavailable, so their live routes are not enabled. The Mini access probe succeeded; a full campaign on the new mixed routing has not yet run. The recovered October 16 campaign completed under the preceding single-model configuration and remains approved for its scheduled publication. Offline validation passed 204 tests. SMTP and n8n management credentials are still required for email and independent workflow fallback activation.
