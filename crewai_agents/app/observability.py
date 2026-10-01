"""Datadog spans and defensive redaction for locally saved/exported audit records."""
import os
import re
import traceback
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
    value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
    value = re.sub(r"(?i)([?&](?:access_token|api_key|token)=)[^\s&#]+", r"\1[REDACTED]", value)
    return value


def error_details(exc):
    """Keep provider diagnostics and stack locations, never request bodies or locals.

    Generic exception strings can contain entire prompts, validation inputs or
    credentials. Only structured provider error fields are eligible for export.
    """
    chain, seen, current = [], set(), exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        entry = {'type': type(current).__name__}
        body = getattr(current, 'body', None)
        response = getattr(current, 'response', None)
        if body is None and response is not None:
            try:
                body = response.json()
            except (ValueError, AttributeError):
                pass
            entry['status_code'] = str(response.status_code)
        if isinstance(body, dict):
            problem = body.get('error', body)
            if isinstance(problem, dict):
                for key in ('message', 'type', 'code', 'param', 'error_subcode', 'fbtrace_id'):
                    value = problem.get(key)
                    if isinstance(value, (str, int)):
                        entry['provider_' + key] = redact(str(value))[:2000]
        for key in ('status_code', 'request_id'):
            value = getattr(current, key, None)
            if isinstance(value, (str, int)):
                entry[key] = redact(str(value))[:200]
        entry['stack'] = '\n'.join(
            f'{frame.filename}:{frame.lineno} in {frame.name}'
            for frame in traceback.extract_tb(current.__traceback__)[-20:])
        chain.append(entry)
        current = current.__cause__ or current.__context__
    root = chain[-1]
    message = next((e['provider_message'] for e in reversed(chain) if e.get('provider_message')),
                   f"{root['type']}; inspect error.stack and error.causes for failing code")
    return redact({'kind': root['type'], 'message': message,
                   'stack': '\nCaused by:\n'.join(e['type'] + '\n' + e['stack'] for e in chain),
                   'causes': chain})


def trace_context():
    if os.getenv('DD_TRACE_ENABLED', 'false').lower() not in {'true', '1'} and os.getenv('DD_LLMOBS_ENABLED', '0').lower() not in {'true', '1'}:
        return {}
    from ddtrace import tracer
    span = tracer.current_span()
    if span is None:
        return {}
    # Datadog accepts 128-bit trace IDs as 32-character hex strings.
    trace_id = f'{span.trace_id:032x}' if span.trace_id > 2**64 - 1 else str(span.trace_id)
    return {'dd.trace_id': trace_id, 'dd.span_id': str(span.span_id)}


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
