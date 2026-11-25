"""Runs Relay's real start-up tracing against a fake LangSmith OTLP endpoint.

tests/test_telemetry.py runs this in a fresh interpreter: OpenTelemetry's global tracer
provider can be set once per process, and langsmith caches the environment it reads.
It prints one JSON object describing what reached the endpoint.
"""

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Import the app the way __main__ does before telemetry starts, so a cached environment
# read inside langsmith would show up here as a missing LangChain span.
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tracers.langchain import wait_for_all_tracers
from langgraph.graph import START, StateGraph
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from relay_agents.api import create_app
from relay_agents.graph import GraphState
from relay_agents.service import CaseService
from relay_agents.telemetry import setup_telemetry, tracer
from relay_agents.tenants import load_tenants
from relay_agents.wiring import build_deps

received: list[dict[str, object]] = []
FAILURE_DETAIL = "upstream said: private inquiry body"


def explode(state: GraphState) -> GraphState:
    raise RuntimeError(FAILURE_DETAIL)


class FakeLangSmith(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["content-length"]))
        request = ExportTraceServiceRequest.FromString(body)
        spans = [
            {
                "name": span.name,
                "trace": span.trace_id.hex(),
                "id": span.span_id.hex(),
                "parent": span.parent_span_id.hex(),
                "status": span.status.code,
                "attributes": {a.key: a.value.string_value for a in span.attributes},
            }
            for resource in request.resource_spans
            for scope in resource.scope_spans
            for span in scope.spans
        ]
        received.append(
            {
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "raw": body.decode("latin-1"),
                "spans": spans,
            }
        )
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), FakeLangSmith)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["LANGSMITH_ENDPOINT"] = f"http://127.0.0.1:{server.server_port}/"

    provider = setup_telemetry("relay-agents")
    assert provider is not None

    service = CaseService(build_deps(load_tenants(Path(sys.argv[1])), {"RELAY_OFFLINE": "1"}))
    app = create_app(service, offline=True)
    FastAPIInstrumentor.instrument_app(app, exclude_spans=["receive", "send"])
    accepted = TestClient(app).post(
        "/runs/intake",
        json={
            "tenant": "bun2too",
            "idempotencyKey": "trace-probe",
            "intake": {"channel": "web_widget", "message": "How do I send a private inquiry?"},
        },
    )

    async def model_call() -> None:
        with tracer.start_as_current_span("relay.probe"):
            model = GenericFakeChatModel(messages=iter([AIMessage("hello")]))
            await model.ainvoke("hi", config={"run_name": "probe-model"})

    asyncio.run(model_call())

    # A run that fails inside a node, with customer text in the exception's message.
    failing = StateGraph(GraphState)
    failing.add_node("explode", explode)
    failing.add_edge(START, "explode")
    service._graph = failing.compile()
    failed_case = accepted.json()["caseId"]
    asyncio.run(service.run("bun2too", failed_case))
    wait_for_all_tracers()
    provider.force_flush()
    server.shutdown()
    print(json.dumps({"accepted": accepted.json(), "failed_case": failed_case, "posts": received}))


if __name__ == "__main__":
    main()
