"""Explicit per-role routing; missing credentials never trigger an implicit provider swap."""
import functools
import os

ROLES = {'product_owner', 'business_analyst', 'researcher', 'creative', 'writer',
         'engineering', 'tester', 'editor', 'delivery'}
COMPLEX = {'researcher', 'writer', 'engineering', 'tester', 'editor'}


def route(role, settings):
    if role not in ROLES:
        raise ValueError('Unknown agent role')
    enabled = os.getenv('MODEL_ROUTING_ENABLED', 'false').lower() == 'true'
    tier = 'complex' if role in COMPLEX else 'routine'
    model = (os.getenv('LLM_MODEL_' + role.upper()) or os.getenv('LLM_' + tier.upper() + '_MODEL')
             or settings['model']) if enabled else settings['model']
    provider = model.split('/', 1)[0] if '/' in model else 'openai'
    if provider not in {'openai', 'anthropic', 'gemini'}:
        raise ValueError('Model route must use openai/, anthropic/, or gemini/')
    key = {'openai': 'OPENAI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY', 'gemini': 'GEMINI_API_KEY'}[provider]
    if enabled and not os.getenv(key):
        raise ValueError(f'{key} is required for {role} model route')
    default = min(settings['max_output_tokens'], 2500 if tier == 'routine' and role != 'delivery' else 6000)
    cap = int(os.getenv('LLM_MAX_TOKENS_' + role.upper(), str(default))) if enabled else settings['max_output_tokens']
    if not 512 <= cap <= 16000:
        raise ValueError('Agent output cap must be between 512 and 16000')
    return dict(model=model, provider=provider, tier=tier if enabled else 'legacy', max_output_tokens=cap)


def llm_options(selected, settings):
    provider = selected['provider']
    options = dict(model=selected['model'], timeout=settings['request_timeout_seconds'], max_retries=0)
    cap_key = {'openai': 'max_completion_tokens', 'anthropic': 'max_tokens', 'gemini': 'max_output_tokens'}[provider]
    options[cap_key] = selected['max_output_tokens']
    if provider == 'gemini':
        # The pinned Gemini adapter does not forward generic timeout/max_retries.
        # Google uses milliseconds and counts the initial call as attempt one.
        options['api_key'] = os.getenv('GEMINI_API_KEY')
        options['client_params'] = {'http_options': {
            'timeout': settings['request_timeout_seconds'] * 1000,
            'retry_options': {'attempts': 1}}}

    # OpenAI-specific reasoning parameters must never leak to other providers/models.
    name = selected['model'].rsplit('/', 1)[-1]
    if provider == 'openai' and name.startswith(('gpt-5', 'gpt-6', 'o1', 'o3', 'o4')):
        options['reasoning_effort'] = settings['reasoning_effort'] or 'low'
    return options


def enable_prompt_cache(llm, provider):
    if provider != 'anthropic' or os.getenv('ANTHROPIC_PROMPT_CACHE_ENABLED', 'true').lower() != 'true':
        return
    original = llm.call
    @functools.wraps(original)
    def call(messages, *args, **kwargs):
        # Mark only stable system text; never mutate CrewAI's conversation history.
        if isinstance(messages, list):
            messages = [dict(m, cache_breakpoint=True) if isinstance(m, dict) and m.get('role') == 'system'
                        else m for m in messages]
        return original(messages, *args, **kwargs)
    object.__setattr__(llm, 'call', call)
