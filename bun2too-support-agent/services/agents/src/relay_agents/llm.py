import os
from collections.abc import Mapping
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

# LangChain provider prefix -> Cloudflare AI Gateway provider path. Add a row per provider.
_GATEWAY_PROVIDERS = {"anthropic": "anthropic"}


def _gateway(spec: str, env: Mapping[str, str]) -> dict[str, Any]:
    """Route model calls through Cloudflare AI Gateway (ADR 0007). Empty when no gateway is set."""
    account, gateway = env.get("CF_AIG_ACCOUNT_ID"), env.get("CF_AIG_GATEWAY_ID")
    if not account and not gateway:
        return {}
    if not (account and gateway):
        raise ValueError("set both CF_AIG_ACCOUNT_ID and CF_AIG_GATEWAY_ID, or neither")
    provider = spec.split(":", 1)[0]
    route = _GATEWAY_PROVIDERS.get(provider)
    if route is None:
        raise ValueError(
            f"no AI Gateway route for provider {provider!r}; add it to _GATEWAY_PROVIDERS"
        )
    # Customer text is in every prompt: keep token, cost and latency metadata, never the payload.
    headers = {"cf-aig-collect-log-payload": "false"}
    if token := env.get("CF_AIG_TOKEN"):
        headers = {"cf-aig-authorization": f"Bearer {token}", **headers}
    # AI Gateway reads the provider key from x-api-key; the SDK sends it as a bearer token only.
    if route == "anthropic" and (key := env.get("ANTHROPIC_API_KEY")):
        headers["x-api-key"] = key
    return {
        "base_url": f"https://gateway.ai.cloudflare.com/v1/{account}/{gateway}/{route}",
        "default_headers": headers,
    }


def chat_model(spec: str, env: Mapping[str, str] = os.environ) -> BaseChatModel:
    model: BaseChatModel = init_chat_model(spec, **_gateway(spec, env))
    return model


def structured[T: BaseModel](model: BaseChatModel, schema: type[T]) -> Runnable[Any, Any]:
    return model.with_structured_output(schema, method="json_schema")
