"""Datadog spans and defensive redaction for locally saved/exported audit records."""
import os
import re
import sys
import traceback
from contextlib import contextmanager


def redact(value):
    if isinstance(value, dict):
        numeric_usage = {'max_output_tokens', 'max_tokens', 'input_tokens', 'output_tokens', 'prompt_tokens', 'completion_tokens',
                         'total_tokens', 'cached_prompt_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens',
                         'cached_tokens', 'reasoning_tokens', 'cache_creation_tokens'}
        return {k: ("[REDACTED]" if not (k.rsplit('.', 1)[-1] in numeric_usage and isinstance(v, (int, float)) and not isinstance(v, bool)) and re.search(r"password|api[_-]?key|token|authorization|secret", k, re.I)
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
    value = re.sub(r"\blsv2_[A-Za-z0-9_-]+", "[REDACTED]", value)
    value = re.sub(r"\bxox[baprs]-[A-Za-z0-9-]+", "[REDACTED]", value)
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
            try:
                entry['retry_after_seconds'] = min(3600, max(0, int(response.headers.get('Retry-After', '0'))))
            except (ValueError, AttributeError):
                pass
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
    from .otel import correlation
    current = correlation()
    if current:
        return current
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
def _optional_llmobs_span(context_factory, annotation):
    """Keep Datadog setup/export failures outside the campaign control path."""
    context = None
    try:
        context = context_factory()
        context.__enter__()
        annotation()
    except Exception:
        if context is not None:
            try:
                context.__exit__(*sys.exc_info())
            except Exception:
                pass
        yield
        return
    try:
        yield
    except BaseException:
        details = sys.exc_info()
        try:
            context.__exit__(*details)
        except Exception:
            pass
        raise
    else:
        try:
            context.__exit__(None, None, None)
        except Exception:
            pass


@contextmanager
def workflow_span(run_id):
    if os.getenv("DD_LLMOBS_ENABLED", "0").lower() not in {"1", "true"}:
        yield
        return
    from ddtrace.llmobs import LLMObs
    try:
        LLMObs.register_processor(redact_span)
    except Exception:
        yield
        return
    with _optional_llmobs_span(
            lambda: LLMObs.workflow(name="bun2too.marketing.run", session_id=run_id),
            lambda: LLMObs.annotate(tags={"run_id": run_id})):
        yield


def redact_span(span):
    capture = os.getenv('TELEMETRY_CAPTURE_CONTENT', 'false').lower() == 'true'
    span.input = redact(span.input) if capture else None
    span.output = redact(span.output) if capture else None
    span.metadata = redact(span.metadata)
    return span


@contextmanager
def action_span(run_id, name, details):
    if os.getenv("DD_LLMOBS_ENABLED", "0").lower() not in {"1", "true"}:
        yield
        return
    from ddtrace.llmobs import LLMObs
    try:
        LLMObs.register_processor(redact_span)
    except Exception:
        yield
        return
    with _optional_llmobs_span(
            lambda: LLMObs.tool(name=name, session_id=run_id),
            lambda: LLMObs.annotate(input_data=redact(details), tags={"run_id": run_id})):
        yield
