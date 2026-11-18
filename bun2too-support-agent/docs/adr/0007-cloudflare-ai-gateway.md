# 0007: Route model calls through Cloudflare AI Gateway

- Status: accepted
- Date: 2026-11-18

## Context

The agents service called the model provider directly. Spend limits, rate limits, retries, provider fallback and per-call analytics would each have to be built and run by us. We want those controls with as little to maintain as possible, close to where traffic enters the network.

Cloudflare AI Gateway is a managed proxy on Cloudflare's edge network. Pointing a provider SDK's base URL at it adds analytics (requests, tokens, cost, latency, errors), rate limiting, caching, retries and fallback, with no service for us to deploy. It supports Anthropic natively at `https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/anthropic`.

Every prompt carries customer text, and the architecture keeps raw messages out of logs and traces.

## Decision

All model calls in qa and prod go through Cloudflare AI Gateway, one gateway per environment (`relay-qa`, `relay-prod`). `relay_agents.llm.chat_model` is the only place that builds models, so it is the only place that knows about the gateway:

- `CF_AIG_ACCOUNT_ID` and `CF_AIG_GATEWAY_ID` set the base URL. With neither set, calls go straight to the provider (local development, offline dev). Setting only one is an error.
- `CF_AIG_TOKEN` authenticates to the gateway (`cf-aig-authorization`). Gateways run with **Authenticated Gateway** on, so a leaked URL cannot spend our quota.
- Every call sends `cf-aig-collect-log-payload: false`, so Cloudflare keeps token, cost and latency metadata but never prompts or responses. This is enforced in code, not left to a dashboard setting.
- The provider key is sent as `x-api-key`, where AI Gateway reads it. The Anthropic key stays in our secrets.

The settings arrive through `SUPPORT_RUNTIME_SECRETS` like every other runtime secret ([runtime secrets](../runtime-secrets.md)). The gateways are created once in the Cloudflare dashboard; they hold no state we need to manage as code.

## Consequences

- Spend, rate limits and per-call analytics are configured in Cloudflare per environment, without code or deploys. Provider fallback becomes a gateway setting.
- Model calls add one network hop through the nearest Cloudflare location. The agents service itself still runs on Railway, so this is a proxy at the edge, not edge compute for our code.
- Adding another provider means adding its route to `_GATEWAY_PROVIDERS` in `llm.py`; an unmapped provider fails at start-up instead of silently bypassing the gateway.
- Response caching stays off by default: support conversations are personal, and a cached answer could reach the wrong customer.
- Cloudflare becomes a dependency on the model path. If the gateway is down, setting both `CF_AIG_*` IDs to empty and redeploying routes calls directly to the provider.
- Not decided here: moving `apps/gateway` (Hono) onto Cloudflare Workers. Hono runs on Workers, so that is possible later, but it changes hosting, networking to the agents service and the deploy pipeline, and needs its own ADR.
- To verify on the first qa deploy: the intake journey succeeds, and the gateway's analytics show the calls with no stored payloads. The client also sends the provider key as a bearer token (the SDK default, which LangChain cannot remove); if the gateway rejects that, `llm.py` must drop the header.
