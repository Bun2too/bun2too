import os
from collections.abc import Mapping
from typing import Final

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

ATTR_TENANT: Final = "relay.tenant"
ATTR_CASE_ID: Final = "relay.case_id"
# LangSmith groups runs that share a thread: one case, from intake through every reply.
ATTR_THREAD_ID: Final = "langsmith.metadata.thread_id"
ATTR_GEN_AI_SYSTEM: Final = "gen_ai.system"
ATTR_GEN_AI_MODEL: Final = "gen_ai.request.model"
ATTR_GEN_AI_INPUT_TOKENS: Final = "gen_ai.usage.input_tokens"
ATTR_GEN_AI_OUTPUT_TOKENS: Final = "gen_ai.usage.output_tokens"

tracer = trace.get_tracer("relay.agents")


LANGSMITH_DEFAULT_ENDPOINT: Final = "https://api.smith.langchain.com"
_LANGSMITH_REQUIRED: Final = (
    "LANGSMITH_API_KEY",
    "LANGSMITH_AGENT_ID",
    "LANGSMITH_AGENT_ENVIRONMENT",
)
_AGENT_ENVIRONMENTS: Final = ("local", "development", "staging", "production")


def langsmith_export(env: Mapping[str, str]) -> tuple[str, dict[str, str]] | None:
    """LangSmith's OTLP endpoint and headers (ADR 0009), or None when tracing is off.

    Partial settings raise: a runtime that half-configures tracing would otherwise drop
    every trace without a word.
    """
    values = {name: env.get(name, "").strip() for name in _LANGSMITH_REQUIRED}
    if not any(values.values()):
        return None
    missing = [name for name, value in values.items() if not value]
    if missing:
        needs = ", ".join(_LANGSMITH_REQUIRED)
        raise ValueError(f"LangSmith tracing needs {needs}; missing {', '.join(missing)}")
    environment = values["LANGSMITH_AGENT_ENVIRONMENT"]
    if environment not in _AGENT_ENVIRONMENTS:
        raise ValueError(
            f"LANGSMITH_AGENT_ENVIRONMENT must be one of {', '.join(_AGENT_ENVIRONMENTS)}"
        )
    for legacy in ("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT"):
        if env.get(legacy, "").strip():
            raise ValueError(f"unset {legacy}: LangSmith rejects a project with agent addressing")
    base = (env.get("LANGSMITH_ENDPOINT", "").strip() or LANGSMITH_DEFAULT_ENDPOINT).rstrip("/")
    headers = {
        "x-api-key": values["LANGSMITH_API_KEY"],
        "Langsmith-Agent-Id": values["LANGSMITH_AGENT_ID"],
        "Langsmith-Agent-Environment": environment,
    }
    if workspace := env.get("LANGSMITH_WORKSPACE_ID", "").strip():
        headers["X-Tenant-Id"] = workspace
    return f"{base}/otel/v1/traces", headers


def setup_telemetry(
    service_name: str, env: Mapping[str, str] = os.environ
) -> TracerProvider | None:
    """Export spans to LangSmith and/or an OTLP collector; None when neither is set."""
    langsmith = langsmith_export(env)
    collector = env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if langsmith is None and not collector:
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if collector:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if langsmith is not None:
        endpoint, headers = langsmith
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
        )
    # LangGraph nodes and model calls become spans of this provider, inside the case's
    # trace: one instrumentation, so the SDK never sends a second copy of its own.
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_TRACING_MODE"] = "otel"
    # Run inputs and outputs carry customer text. They stay in the process unless an
    # environment sets these to "false" (ADR 0009).
    os.environ.setdefault("LANGSMITH_HIDE_INPUTS", "true")
    os.environ.setdefault("LANGSMITH_HIDE_OUTPUTS", "true")
    trace.set_tracer_provider(provider)
    return provider


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
