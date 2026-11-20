from typing import Any, cast

import httpx
import pytest
from anthropic._models import FinalRequestOptions
from langchain_core.language_models import BaseChatModel
from langchain_core.load import dumpd

from relay_agents.llm import chat_model, check_models
from relay_agents.tenants import load_tenants
from relay_agents.wiring import DEFAULT_TENANTS_DIR, build_deps

SPEC = "anthropic:claude-opus-5-5"
GATEWAY = {
    "CF_AIG_ACCOUNT_ID": "acct123",
    "CF_AIG_GATEWAY_ID": "relay-qa",
    "CF_AIG_TOKEN": "gateway-token-secret",
}


@pytest.fixture(autouse=True)
def _provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "provider-key-secret")
    for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_URL"):
        monkeypatch.delenv(name, raising=False)


def _sent(model: BaseChatModel) -> httpx.Request:
    """The request the model's async client would put on the wire for a messages call."""
    client = cast(Any, model)._async_client
    request: httpx.Request = client._build_request(
        FinalRequestOptions.construct(method="post", url="/v1/messages", json_data={})
    )
    return request


def test_without_gateway_settings_calls_the_provider_directly() -> None:
    request = _sent(chat_model(SPEC, env={}))
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert not any(name.startswith("cf-aig-") for name in request.headers)


def test_a_token_without_gateway_ids_is_the_rollback_and_calls_the_provider_directly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Rolling back (ADR 0007) clears both IDs and may leave the token set.
    token_only = {"CF_AIG_TOKEN": GATEWAY["CF_AIG_TOKEN"]}
    request = _sent(chat_model(SPEC, env=token_only))
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert not any(name.startswith("cf-aig-") for name in request.headers)
    check_models([SPEC], env=token_only)
    assert "bypass Cloudflare AI Gateway" in caplog.text


def test_with_gateway_settings_routes_through_cloudflare_ai_gateway() -> None:
    request = _sent(chat_model(SPEC, env=GATEWAY))
    assert (
        str(request.url)
        == "https://gateway.ai.cloudflare.com/v1/acct123/relay-qa/anthropic/v1/messages"
    )
    assert request.headers["cf-aig-authorization"] == "Bearer gateway-token-secret"
    assert request.headers["cf-aig-collect-log-payload"] == "false"
    assert request.headers["cf-aig-skip-cache"] == "true"
    assert request.headers["authorization"] == "Bearer provider-key-secret"
    assert "x-api-key" not in request.headers


def test_secrets_stay_out_of_repr_and_serialised_model() -> None:
    model = chat_model(SPEC, env=GATEWAY)
    _sent(model)  # build the client, so any cached state is populated too
    for shown in (repr(model), str(dumpd(model))):
        assert "gateway-token-secret" not in shown
        assert "provider-key-secret" not in shown


@pytest.mark.parametrize(
    "env",
    [
        {"CF_AIG_ACCOUNT_ID": "acct123"},
        {"CF_AIG_ACCOUNT_ID": "acct123", "CF_AIG_GATEWAY_ID": "relay-qa"},
        {**GATEWAY, "CF_AIG_GATEWAY_ID": "  "},
    ],
)
def test_incomplete_gateway_settings_fail_loudly(env: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="CF_AIG_ACCOUNT_ID, CF_AIG_GATEWAY_ID and CF_AIG_TOKEN"):
        chat_model(SPEC, env=env)


def test_unmapped_provider_through_gateway_fails_loudly() -> None:
    with pytest.raises(ValueError, match="no AI Gateway route for provider 'openai'"):
        chat_model("openai:gpt-x", env=GATEWAY)


def test_check_models_fails_at_start_up_on_a_broken_gateway() -> None:
    with pytest.raises(ValueError, match="CF_AIG_TOKEN"):
        check_models([SPEC], env={k: v for k, v in GATEWAY.items() if k != "CF_AIG_TOKEN"})


def test_check_models_warns_when_the_gateway_is_bypassed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check_models([SPEC], env={})
    assert "bypass Cloudflare AI Gateway" in caplog.text
    caplog.clear()
    check_models([SPEC], env=GATEWAY)
    assert not caplog.text


def test_live_service_refuses_to_start_with_a_broken_gateway() -> None:
    tenants = load_tenants(DEFAULT_TENANTS_DIR)
    with pytest.raises(ValueError, match="CF_AIG_TOKEN"):
        build_deps(tenants, {"CF_AIG_ACCOUNT_ID": "acct123", "CF_AIG_GATEWAY_ID": "relay-qa"})
