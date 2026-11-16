import functools
import os
from collections.abc import Awaitable, Callable
from typing import Any, Final

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

ATTR_TENANT: Final = "relay.tenant"
ATTR_CASE_ID: Final = "relay.case_id"
ATTR_NODE: Final = "relay.node"
ATTR_GEN_AI_SYSTEM: Final = "gen_ai.system"
ATTR_GEN_AI_MODEL: Final = "gen_ai.request.model"
ATTR_GEN_AI_INPUT_TOKENS: Final = "gen_ai.usage.input_tokens"
ATTR_GEN_AI_OUTPUT_TOKENS: Final = "gen_ai.usage.output_tokens"

TRACED_MARKER: Final = "__relay_traced__"

tracer = trace.get_tracer("relay.agents")


def setup_telemetry(service_name: str) -> None:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


NodeFn = Callable[..., Awaitable[dict[str, Any]]]


def traced_node(name: str) -> Callable[[NodeFn], NodeFn]:
    def decorate(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
            with tracer.start_as_current_span(f"relay.node.{name}") as span:
                span.set_attribute(ATTR_NODE, name)
                span.set_attribute(ATTR_CASE_ID, str(state.get("case_id", "")))
                span.set_attribute(ATTR_TENANT, str(state.get("tenant", "")))
                return await fn(state, *args, **kwargs)

        setattr(wrapper, TRACED_MARKER, True)
        return wrapper

    return decorate


def is_traced(fn: object) -> bool:
    target = fn.func if isinstance(fn, functools.partial) else fn
    return bool(getattr(target, TRACED_MARKER, False))
