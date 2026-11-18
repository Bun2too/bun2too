import pytest

from relay_agents.llm import chat_model

GATEWAY = {
    "CF_AIG_ACCOUNT_ID": "acct123",
    "CF_AIG_GATEWAY_ID": "relay-qa",
    "CF_AIG_TOKEN": "t0k",
    "ANTHROPIC_API_KEY": "sk-test",
}


@pytest.fixture(autouse=True)
def _provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def test_without_gateway_settings_calls_the_provider_directly() -> None:
    model = chat_model("anthropic:claude-opus-5-5", env={})
    fields = vars(model)
    assert type(model).__name__ == "ChatAnthropic"
    assert fields["anthropic_api_url"] == "https://api.anthropic.com"
    assert not fields["default_headers"]


def test_with_gateway_settings_routes_through_cloudflare_ai_gateway() -> None:
    model = chat_model("anthropic:claude-opus-5-5", env=GATEWAY)
    fields = vars(model)
    assert type(model).__name__ == "ChatAnthropic"
    assert (
        fields["anthropic_api_url"]
        == "https://gateway.ai.cloudflare.com/v1/acct123/relay-qa/anthropic"
    )
    assert fields["default_headers"] == {
        "cf-aig-authorization": "Bearer t0k",
        "cf-aig-collect-log-payload": "false",
        "x-api-key": "sk-test",
    }


def test_gateway_never_stores_prompts_even_without_a_token() -> None:
    env = {k: v for k, v in GATEWAY.items() if k != "CF_AIG_TOKEN"}
    model = chat_model("anthropic:claude-opus-5-5", env=env)
    fields = vars(model)
    assert type(model).__name__ == "ChatAnthropic"
    assert fields["default_headers"] == {
        "cf-aig-collect-log-payload": "false",
        "x-api-key": "sk-test",
    }


def test_half_configured_gateway_fails_loudly() -> None:
    with pytest.raises(ValueError, match="CF_AIG_ACCOUNT_ID and CF_AIG_GATEWAY_ID"):
        chat_model("anthropic:claude-opus-5-5", env={"CF_AIG_ACCOUNT_ID": "acct123"})


def test_unmapped_provider_through_gateway_fails_loudly() -> None:
    with pytest.raises(ValueError, match="no AI Gateway route for provider 'openai'"):
        chat_model("openai:gpt-x", env=GATEWAY)
