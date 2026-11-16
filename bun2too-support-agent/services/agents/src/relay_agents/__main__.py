import logging
import os

import uvicorn
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from relay_agents.api import create_app
from relay_agents.telemetry import setup_telemetry
from relay_agents.wiring import build_service


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    setup_telemetry("relay-agents")
    HTTPXClientInstrumentor().instrument()
    app = create_app(build_service(), offline=os.environ.get("RELAY_OFFLINE") == "1")
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")
    port = int(os.environ.get("RELAY_AGENTS_PORT", "8000"))
    print(f"relay-agents listening on :{port}", flush=True)
    uvicorn.run(
        app, host=os.environ.get("RELAY_AGENTS_HOST", "127.0.0.1"), port=port, log_level="warning"
    )


if __name__ == "__main__":
    main()
