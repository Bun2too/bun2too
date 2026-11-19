import logging
import os
from collections.abc import Iterable, Mapping
from functools import cached_property
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel, PrivateAttr, SecretStr

log = logging.getLogger("relay.agents")

_GATEWAY_URL = "https://gateway.ai.cloudflare.com/v1/{account}/{gateway}/anthropic"
# Customer text is in every prompt: Cloudflare keeps token, cost and latency metadata but
# never the payload, and never answers one customer with another's cached reply.
_GATEWAY_HEADERS = {"cf-aig-collect-log-payload": "false", "cf-aig-skip-cache": "true"}


class _GatewayChatAnthropic(ChatAnthropic):
    """ChatAnthropic that sends the AI Gateway token without keeping it in model fields.

    Model fields, default_headers included, appear in repr(), dumpd() and the `serialized`
    payload every LangChain callback receives. A private attribute appears in none of them.
    """

    _gateway_token: SecretStr = PrivateAttr()

    @cached_property
    def _client_params(self) -> dict[str, Any]:
        params = super()._client_params
        auth = {"cf-aig-authorization": f"Bearer {self._gateway_token.get_secret_value()}"}
        return {**params, "default_headers": {**params["default_headers"], **auth}}


def _gateway(env: Mapping[str, str]) -> tuple[str, SecretStr] | None:
    """The AI Gateway URL and token (ADR 0007), or None when both gateway IDs are unset."""
    account, gateway, token = (
        env.get(name, "").strip()
        for name in ("CF_AIG_ACCOUNT_ID", "CF_AIG_GATEWAY_ID", "CF_AIG_TOKEN")
    )
    if not account and not gateway:
        return None
    if not (account and gateway and token):
        raise ValueError(
            "AI Gateway needs CF_AIG_ACCOUNT_ID, CF_AIG_GATEWAY_ID and CF_AIG_TOKEN; "
            "clear both IDs to call the provider directly"
        )
    return _GATEWAY_URL.format(account=account, gateway=gateway), SecretStr(token)


def chat_model(spec: str, env: Mapping[str, str] = os.environ) -> BaseChatModel:
    gateway = _gateway(env)
    if gateway is None:
        model: BaseChatModel = init_chat_model(spec)
        return model
    provider, _, name = spec.partition(":")
    if provider != "anthropic":
        raise ValueError(f"no AI Gateway route for provider {provider!r}")
    url, token = gateway
    routed = _GatewayChatAnthropic(model=name, base_url=url, default_headers=_GATEWAY_HEADERS)
    routed._gateway_token = token
    return routed


def check_models(specs: Iterable[str], env: Mapping[str, str] = os.environ) -> None:
    """Fail at start-up, not on the first intake, when a model or the gateway is misconfigured."""
    for spec in specs:
        chat_model(spec, env)
    if _gateway(env) is None:
        log.warning("CF_AIG_* IDs unset: model calls bypass Cloudflare AI Gateway (ADR 0007)")


def structured[T: BaseModel](model: BaseChatModel, schema: type[T]) -> Runnable[Any, Any]:
    return model.with_structured_output(schema, method="json_schema")
