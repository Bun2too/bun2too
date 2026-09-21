"""Datadog spans and defensive redaction for locally saved/exported audit records."""
import os
import re
from contextlib import contextmanager


def redact(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if re.search(r"password|api[_-]?key|token|authorization|secret", k, re.I)
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    for key, secret in os.environ.items():
        if len(secret) >= 8 and re.search(r"PASSWORD|API_KEY|TOKEN|SECRET", key):
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)(Bearer\s+)[^\s\"']+", r"\1[REDACTED]", value)
    return value


@contextmanager
def workflow_span(run_id):
    if os.getenv("DD_LLMOBS_ENABLED", "0").lower() not in {"1", "true"}:
        yield
        return
    from ddtrace.llmobs import LLMObs
    LLMObs.register_processor(redact_span)
    with LLMObs.workflow(name="bun2too.marketing.run", session_id=run_id):
        LLMObs.annotate(tags={"run_id": run_id})
        yield


def redact_span(span):
    span.input = redact(span.input)
    span.output = redact(span.output)
    span.metadata = redact(span.metadata)
    return span


@contextmanager
def action_span(run_id, name, details):
    if os.getenv("DD_LLMOBS_ENABLED", "0").lower() not in {"1", "true"}:
        yield
        return
    from ddtrace.llmobs import LLMObs
    LLMObs.register_processor(redact_span)
    with LLMObs.tool(name=name, session_id=run_id):
        LLMObs.annotate(input_data=redact(details), tags={"run_id": run_id})
        yield
