"""Load local configuration before ddtrace-run imports/instruments CrewAI."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
os.environ.setdefault("DD_SITE", "us5.datadoghq.com")
os.environ.setdefault("DD_LLMOBS_ML_APP", "bun2too-marketing-crew-team")
os.environ.setdefault("DD_LLMOBS_AGENTLESS_ENABLED", "1")
os.environ.setdefault("DD_SERVICE", "bun2too-marketing-api")
# Railway has no local Datadog Agent. LLMObs agentless export remains enabled.
os.environ.setdefault("DD_TRACE_ENABLED", "false")
command = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
           "--port", os.getenv("PORT", "8000")]
if os.getenv("DD_LLMOBS_ENABLED", "0").lower() in {"1", "true"}:
    if not os.getenv("DD_API_KEY", "").strip():
        raise SystemExit("DD_LLMOBS_ENABLED requires DD_API_KEY in service secrets")
    command = [str(Path(sys.executable).with_name("ddtrace-run")), *command]
os.chdir(Path(__file__).resolve().parent)
os.execv(command[0], command)
