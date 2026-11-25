import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from relay_agents.telemetry import langsmith_export, without_error_text

REPO = Path(__file__).resolve().parents[3]
KEY = "trace-probe-key"
LANGSMITH = {
    "LANGSMITH_API_KEY": KEY,
    "LANGSMITH_AGENT_ID": "bun2too-support-agent",
    "LANGSMITH_AGENT_ENVIRONMENT": "staging",
}


def test_export_is_off_when_nothing_is_set() -> None:
    assert langsmith_export({}) is None


def test_export_targets_langsmith_otlp_with_agent_headers() -> None:
    endpoint, headers = langsmith_export(LANGSMITH) or ("", {})
    assert endpoint == "https://api.smith.langchain.com/otel/v1/traces"
    assert headers == {
        "x-api-key": KEY,
        "Langsmith-Agent-Id": "bun2too-support-agent",
        "Langsmith-Agent-Environment": "staging",
    }


def test_endpoint_and_workspace_are_configurable() -> None:
    env = {
        **LANGSMITH,
        "LANGSMITH_ENDPOINT": "https://eu.api.smith.langchain.com/",
        "LANGSMITH_WORKSPACE_ID": "ws-1",
    }
    endpoint, headers = langsmith_export(env) or ("", {})
    assert endpoint == "https://eu.api.smith.langchain.com/otel/v1/traces"
    assert headers["X-Tenant-Id"] == "ws-1"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.smith.langchain.com",
        "http://collector.example",
        "ftp://api.smith.langchain.com",
        "api.smith.langchain.com",
        "https://",
        "https://user:pass@api.smith.langchain.com",
        "https://api.smith.langchain.com?x=1",
        "https://api.smith.langchain.com#x",
        "http://127.0.0.1.collector.example",
    ],
)
def test_an_endpoint_that_could_leak_the_key_fails_loudly(endpoint: str) -> None:
    """The key rides in a header, so it only goes to an HTTPS URL with nothing extra."""
    with pytest.raises(ValueError, match="LANGSMITH_ENDPOINT") as raised:
        langsmith_export({**LANGSMITH, "LANGSMITH_ENDPOINT": endpoint})
    assert KEY not in str(raised.value)


@pytest.mark.parametrize("host", ["127.0.0.1:4318", "localhost:4318", "[::1]:4318"])
def test_plain_http_is_allowed_only_on_loopback(host: str) -> None:
    endpoint, _ = langsmith_export({**LANGSMITH, "LANGSMITH_ENDPOINT": f"http://{host}"}) or (
        "",
        {},
    )
    assert endpoint == f"http://{host}/otel/v1/traces"


@pytest.mark.parametrize("missing", sorted(LANGSMITH))
def test_incomplete_settings_fail_loudly(missing: str) -> None:
    env = {k: v for k, v in LANGSMITH.items() if k != missing}
    with pytest.raises(ValueError, match=missing):
        langsmith_export(env)


def test_unknown_agent_environment_fails_loudly() -> None:
    with pytest.raises(ValueError, match="LANGSMITH_AGENT_ENVIRONMENT"):
        langsmith_export({**LANGSMITH, "LANGSMITH_AGENT_ENVIRONMENT": "qa"})


@pytest.mark.parametrize(
    "legacy", ["LANGSMITH_PROJECT", "LANGCHAIN_PROJECT", "LANGSMITH_SESSION", "LANGCHAIN_SESSION"]
)
def test_a_project_alongside_agent_addressing_fails_loudly(legacy: str) -> None:
    """LangSmith answers 400 when a project and the agent headers arrive together."""
    with pytest.raises(ValueError, match=legacy):
        langsmith_export({**LANGSMITH, legacy: "anything"})


def test_an_error_leaves_as_its_class_name_only() -> None:
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    with (
        pytest.raises(RuntimeError),
        provider.get_tracer("t").start_as_current_span("failing"),
    ):
        raise RuntimeError("customer wrote: my card is 4111")
    (raw,) = memory.get_finished_spans()
    assert "4111" in str(raw.status.description)

    span = without_error_text(raw)
    assert span.status.description == "RuntimeError"
    (event,) = span.events
    assert dict(event.attributes or {}) == {"exception.type": "RuntimeError"}


def _run_probe(extra: dict[str, str]) -> dict[str, Any]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LANGSMITH_", "LANGCHAIN_", "OTEL_"))
    }
    result = subprocess.run(  # noqa: S603 -- runs this repo's own probe script
        [sys.executable, str(Path(__file__).with_name("trace_probe.py")), str(REPO / "tenants")],
        env={**env, **LANGSMITH, **extra},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    output: dict[str, Any] = json.loads(result.stdout.splitlines()[-1])
    return output


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    return _run_probe({})


CUSTOMER_TEXT = "private inquiry"
FAILURE_DETAIL = "upstream said: private inquiry body"


def test_customer_text_stays_in_the_process_by_default(probe: dict[str, Any]) -> None:
    raw = "".join(post["raw"] for post in probe["posts"])
    assert raw
    assert CUSTOMER_TEXT not in raw
    assert "hello" not in raw


def test_a_failed_run_exports_its_error_class_but_not_its_message(
    probe: dict[str, Any],
) -> None:
    raw = "".join(post["raw"] for post in probe["posts"])
    assert FAILURE_DETAIL not in raw
    failed = next(s for s in _spans(probe) if s["name"] == "relay.case.run" and s["status"] == 2)
    assert failed["attributes"]["relay.case_id"] == probe["failed_case"]


def test_an_environment_can_opt_in_to_payloads() -> None:
    shown = _run_probe({"LANGSMITH_HIDE_INPUTS": "false", "LANGSMITH_HIDE_OUTPUTS": "false"})
    raw = "".join(post["raw"] for post in shown["posts"])
    assert CUSTOMER_TEXT in raw
    assert "hello" in raw


def _spans(probe: dict[str, Any]) -> list[dict[str, Any]]:
    return [span for post in probe["posts"] for span in post["spans"]]


def test_spans_reach_langsmith_with_the_agent_headers(probe: dict[str, Any]) -> None:
    assert probe["posts"], "nothing was exported"
    for post in probe["posts"]:
        assert post["path"] == "/otel/v1/traces"
        assert post["headers"]["x-api-key"] == KEY
        assert post["headers"]["langsmith-agent-id"] == "bun2too-support-agent"
        assert post["headers"]["langsmith-agent-environment"] == "staging"
        assert "langsmith-project" not in post["headers"]


def test_a_case_is_one_trace_from_request_to_every_node(probe: dict[str, Any]) -> None:
    case_id = probe["accepted"]["caseId"]
    trace_id = probe["accepted"]["traceId"]
    in_trace = [s for s in _spans(probe) if s["trace"] == trace_id]
    run = next(s for s in in_trace if s["name"] == "relay.case.run")
    assert run["attributes"]["langsmith.metadata.thread_id"] == case_id
    assert run["attributes"]["relay.case_id"] == case_id
    assert run["attributes"]["langsmith.metadata.tenant"] == "bun2too"

    by_id = {s["id"]: s for s in in_trace}
    graph = next(s for s in in_trace if s["name"] == "LangGraph")
    assert graph["parent"] == run["id"]
    nodes = {s["name"]: s for s in in_trace if s["parent"] == graph["id"]}
    # The offline knowledge answer: every node this case ran is a span, once.
    ran = ["classify", "open_tickets", "run_specialist", "assess", "resolve"]
    assert set(ran) <= set(nodes)
    for name in ran:
        assert nodes[name]["attributes"]["langsmith.metadata.thread_id"] == case_id
        assert nodes[name]["attributes"]["langsmith.metadata.tenant"] == "bun2too"
        assert by_id[nodes[name]["parent"]] is graph
    assert sum(1 for s in in_trace if s["name"] == "classify") == 1


def test_langchain_runs_nest_inside_relays_trace(probe: dict[str, Any]) -> None:
    spans = _spans(probe)
    parent = next(s for s in spans if s["name"] == "relay.probe")
    model = next(s for s in spans if s["name"] == "probe-model")
    assert model["trace"] == parent["trace"]
    assert model["parent"] == parent["id"]
    assert model["attributes"]["langsmith.span.kind"] == "llm"


def test_the_api_key_never_leaves_in_a_span(probe: dict[str, Any]) -> None:
    assert all(KEY not in post["raw"] for post in probe["posts"])
