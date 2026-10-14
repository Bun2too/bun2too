"""Per-instance instrumentation for the pinned CrewAI native LLM adapter.

No global monkey patching. Private event emitters are isolated here and tested
against the pinned CrewAI version to capture actual provider usage/finish reasons.
"""
import functools
import hashlib
import inspect
import json
import math
import os
import time
from contextvars import ContextVar
from pathlib import Path

from . import otel

AGENT = ContextVar('telemetry_agent', default=None)
CALL = ContextVar('telemetry_llm_call', default=None)


def version(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def price(model, usage):
    path = os.getenv('MODEL_PRICING_PATH')
    if not path:
        return {'status': 'unavailable', 'reason': 'pricing_not_configured'}
    config = json.loads(Path(path).read_text())
    rates = config.get('models', {}).get(model)
    if not rates:
        return {'status': 'unavailable', 'reason': 'model_not_priced'}
    required = ('input_per_million', 'cached_input_per_million', 'output_per_million')
    if not config.get('version') or any(not isinstance(rates.get(k), (float, int)) or
                                      not math.isfinite(rates[k]) or rates[k] < 0 for k in required):
        raise ValueError('Pricing requires a version and finite nonnegative USD rates')
    if usage.get('input_tokens') is None or usage.get('output_tokens') is None:
        return {'status': 'unavailable', 'reason': 'provider_usage_missing'}
    cached = min(usage.get('cached_tokens', 0), usage['input_tokens'])
    amount = ((usage['input_tokens'] - cached) * rates['input_per_million'] +
              cached * rates['cached_input_per_million'] + usage['output_tokens'] * rates['output_per_million']) / 1_000_000
    return {'status': 'estimated', 'usd': amount, 'pricing_version': config['version']}


def normalized_usage(data):
    aliases = {'input_tokens': ('input_tokens', 'prompt_tokens'), 'output_tokens': ('output_tokens', 'completion_tokens'),
               'cached_tokens': ('cached_tokens', 'cached_prompt_tokens', 'cache_read_input_tokens'),
               'reasoning_tokens': ('reasoning_tokens',)}
    result = {}
    for target, sources in aliases.items():
        for key in sources:
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                result[target] = int(value)
                break
    return result


def image_usage(response, settings):
    raw = getattr(response, 'usage', None)
    data = raw.model_dump() if raw is not None and hasattr(raw, 'model_dump') else {}
    usage = normalized_usage(data) if isinstance(data, dict) else {}
    cost = {'status': 'unavailable', 'reason': 'image_price_not_configured'}
    try:
        path = os.getenv('MODEL_PRICING_PATH')
        config = json.loads(Path(path).read_text()) if path else {}
        rate = config.get('images', {}).get(settings['model'], {}).get(settings['size'] + ':' + settings['quality'])
        if isinstance(rate, (int, float)) and math.isfinite(rate) and rate >= 0 and config.get('version'):
            cost = {'status': 'estimated', 'usd': rate, 'pricing_version': config['version']}
            otel.measure('gen_ai.client.cost', rate, {'model': settings['model'], 'pricing_version': config['version']}, unit='USD')
    except (OSError, ValueError, TypeError):
        cost = {'status': 'unavailable', 'reason': 'invalid_image_pricing'}
    if cost['status'] != 'estimated':
        otel.measure('gen_ai.client.usage_unavailable', attributes={'model': settings['model']})
    for key, value in usage.items():
        otel.measure('gen_ai.image.token.usage', value, {'model': settings['model'], 'token_type': key}, unit='{token}', histogram=True)
    run = otel.RUN.get()
    if run:
        run['db'].event(run['id'], 'llm_call_finished', operation='image.generate', model=settings['model'],
                        status='completed', usage=usage, cost=cost)


def check_budget(record_event=None):
    run = otel.RUN.get()
    limit = float(os.getenv('RUN_COST_BUDGET_USD', '0'))
    if limit <= 0 or not run:
        return
    if not math.isfinite(limit):
        raise ValueError('Run budget must be a finite USD amount')
    if price(os.getenv('LLM_MODEL', ''), {'input_tokens': 0, 'output_tokens': 0})['status'] != 'estimated':
        raise ValueError('A configured run cost budget requires a versioned model rate card')
    events = run['db'].events(run['id'])
    calls = [event for event in events if event['kind'] == 'llm_call_finished']
    uncertain = any(event.get('cost', {}).get('status') != 'estimated' for event in calls)
    spent = sum(event.get('cost', {}).get('usd', 0) for event in calls)
    if uncertain or spent >= limit:
        if record_event:
            record_event('cost_budget_blocked', status='blocked', reason='usage_unknown' if uncertain else 'budget_reached')
        raise ValueError('Run cost budget reached or prior provider usage is unavailable')


def input_policy(brief):
    """Credential egress check; not a claim of comprehensive prompt-injection detection."""
    from .observability import redact
    with otel.span('guardrail.input', {'policy.name': 'credential-egress', 'policy.version': '1'}) as current:
        content = json.dumps(brief, sort_keys=True)
        passed = redact(content) == content
        current.set_attribute('policy.passed', passed)
        otel.measure('ai.guardrail.decisions', attributes={'operation': 'input', 'outcome': 'passed' if passed else 'blocked'})
        if not passed:
            raise ValueError('Input contains credential material; remove secrets before generation')


def instrument_llm(llm, record_event=None):
    if getattr(llm, '_enterprise_instrumented', False):
        return llm
    original = llm.call
    original_complete = llm._emit_call_completed_event
    signature = inspect.signature(original_complete)

    @functools.wraps(original_complete)
    def completed(*args, **kwargs):
        data = signature.bind(*args, **kwargs).arguments
        call = CALL.get()
        if call is not None:
            usage = normalized_usage(data.get('usage') or {})
            for key, value in usage.items():
                call['usage'][key] = call['usage'].get(key, 0) + value
            call['finish_reason'] = data.get('finish_reason')
            call['response_id'] = data.get('response_id')
        return original_complete(*args, **kwargs)

    original_chunk = llm._emit_stream_chunk_event
    @functools.wraps(original_chunk)
    def chunk(*args, **kwargs):
        call = CALL.get()
        content = args[0] if args else kwargs.get('chunk')
        if call is not None and content and call['first_token'] is None:
            call['first_token'] = time.monotonic()
        return original_chunk(*args, **kwargs)

    @functools.wraps(original)
    def invoke(*args, **kwargs):
        check_budget(record_event)
        model = os.getenv('LLM_MODEL') or str(llm.model)
        provider = str(getattr(llm, 'provider', 'unknown'))
        call = {'usage': {}, 'first_token': None}
        token = CALL.set(call)
        start = time.monotonic()
        outcome = 'completed'
        labels = {'model': model, 'provider': provider}
        try:
            with otel.span('gen_ai.chat', {'gen_ai.operation.name': 'chat', 'gen_ai.provider.name': provider,
                                        'gen_ai.request.model': str(llm.model), 'app.configured_model': model}) as current:
                try:
                    return original(*args, **kwargs)
                except BaseException:
                    outcome = 'failed'
                    raise
                finally:
                    elapsed = time.monotonic() - start
                    usage = call['usage']
                    try:
                        cost = price(model, usage)
                    except (ValueError, OSError, TypeError):
                        cost = {'status': 'unavailable', 'reason': 'invalid_pricing'}
                    for key, value in usage.items():
                        current.set_attribute('gen_ai.usage.' + key, value)
                    if call.get('finish_reason'):
                        current.set_attribute('gen_ai.response.finish_reasons', [call['finish_reason']])
                    if call.get('response_id'):
                        current.set_attribute('gen_ai.response.id', call['response_id'])
                    current.set_attribute('gen_ai.usage.available', bool(usage))
                    otel.measure('gen_ai.client.operation.duration', elapsed, dict(labels, outcome=outcome), unit='s', histogram=True)
                    for key in ('input_tokens', 'output_tokens'):
                        if key in usage:
                            otel.measure('gen_ai.client.token.usage', usage[key], dict(labels, token_type=key), unit='{token}', histogram=True)
                    if call['first_token']:
                        otel.measure('gen_ai.client.time_to_first_token', call['first_token'] - start, labels, unit='s', histogram=True)
                        generation = time.monotonic() - call['first_token']
                        if generation > 0 and 'output_tokens' in usage:
                            otel.measure('gen_ai.client.output_tokens_per_second', usage['output_tokens'] / generation,
                                         labels, unit='{token}/s', histogram=True)
                    if cost['status'] == 'estimated':
                        otel.measure('gen_ai.client.cost', cost['usd'], dict(labels, pricing_version=cost['pricing_version']), unit='USD')
                    else:
                        otel.measure('gen_ai.client.usage_unavailable', attributes=labels)
                    if record_event:
                        record_event('llm_call_finished', agent=AGENT.get(), status=outcome, model=model, usage=usage, cost=cost,
                                     duration_ms=round(elapsed * 1000), finish_reason=call.get('finish_reason'),
                                     measurement_status='available' if usage else 'unavailable')
        finally:
            CALL.reset(token)
    object.__setattr__(llm, 'call', invoke)
    object.__setattr__(llm, '_emit_call_completed_event', completed)
    object.__setattr__(llm, '_emit_stream_chunk_event', chunk)
    object.__setattr__(llm, '_enterprise_instrumented', True)
    return llm


def quality(run, config=None):
    """Deterministic evidence coverage, not a hallucination/faithfulness claim."""
    artifact = run.get('artifact') or {}
    allowed = {source['url'] for source in run.get('source_snapshots', [])}
    citations = [url for article in artifact.get('articles', []) for url in article.get('source_urls', [])]
    reviews = {task['agent']: task.get('structured') or {} for task in run.get('tasks', [])}
    values = {'blocker_count': len(artifact.get('blockers', [])), 'citation_count': len(citations),
              'approved_review_count': sum(reviews.get(role, {}).get('approved_for_publication') is True for role in ('tester', 'editor'))}
    if citations:
        values['citation_source_match'] = sum(url in allowed for url in citations) / len(citations)
    for key, value in values.items():
        otel.measure('ai.quality.score', value, {'evaluator': 'deterministic-v1', 'metric': key}, histogram=True)
    return {'evaluator': 'deterministic-v1', 'scores': values,
            'faithfulness': 'not_evaluated', 'toxicity': 'not_evaluated', 'semantic_drift': 'not_evaluated'}
