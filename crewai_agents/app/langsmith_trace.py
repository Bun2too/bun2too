"""Optional LangSmith mirror of application spans, independent of OTLP/Datadog.

Only application-selected metadata leaves the service by default. Never give the
SDK an application exception: its message/traceback may contain credentials.
"""
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from urllib.parse import urlsplit

from .observability import redact

CURRENT = ContextVar('langsmith_operation', default=None)
HEALTH = {'last_error_type': None, 'export_errors': 0, 'runs_queued': 0}
logger = logging.getLogger(__name__)


def enabled():
    return os.getenv('LANGSMITH_TRACING', 'false').lower() in {'true', '1'}


def configuration():
    endpoint = os.getenv('LANGSMITH_ENDPOINT', 'https://api.smith.langchain.com').rstrip('/')
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('LANGSMITH_ENDPOINT must be HTTPS without credentials, query or fragment')
    if not os.getenv('LANGSMITH_API_KEY', '').strip():
        raise ValueError('Configure LANGSMITH_API_KEY')
    agent = os.getenv('LANGSMITH_AGENT_ID', '').strip()
    environment = os.getenv('LANGSMITH_AGENT_ENVIRONMENT', '').strip()
    project = next((os.getenv(key) for key in ('LANGSMITH_PROJECT', 'LANGCHAIN_PROJECT', 'LANGCHAIN_SESSION') if os.getenv(key)), None)
    if agent or environment:
        if not agent or environment not in {'local', 'development', 'staging', 'production'}:
            raise ValueError('Configure LANGSMITH_AGENT_ID and a valid LANGSMITH_AGENT_ENVIRONMENT together')
        if project:
            raise ValueError('Use LangSmith agent addressing or project addressing, not both')
        from langsmith import AgentAddress
        destination = {'address': AgentAddress(agent, environment)}
    else:
        destination = {'project_name': project or 'crew-ai-agents'}
    return endpoint, destination


def export_error(exc):
    HEALTH['last_error_type'] = type(exc).__name__
    HEALTH['export_errors'] += 1
    logger.warning('LangSmith tracing failed type=%s', type(exc).__name__)


@lru_cache(maxsize=1)
def client():
    from langsmith import Client
    endpoint, _ = configuration()
    return Client(api_url=endpoint, api_key=os.environ['LANGSMITH_API_KEY'],
                  timeout_ms=5000, auto_batch_tracing=True,
                  omit_traced_runtime_info=True, tracing_error_callback=export_error,
                  hide_inputs=redact, hide_outputs=redact, hide_metadata=redact)


def status():
    result = {'enabled': enabled(), **HEALTH}
    if enabled():
        try:
            endpoint, destination = configuration()
            result.update(endpoint=endpoint, destination={key: value.to_api_address() if key == 'address' else value
                                                        for key, value in destination.items()}, configuration='ready')
        except Exception as exc:
            result.update(configuration='invalid', error=redact(str(exc)))
    return result


def flush():
    # Do not create a client on shutdown if tracing was never used.
    if client.cache_info().currsize:
        try:
            client().flush(timeout=5)
        except Exception as exc:
            export_error(exc)


def run_type(name):
    if name.startswith('gen_ai.'):
        return 'llm'
    if name.startswith('retrieval.'):
        return 'retriever'
    if name.startswith(('task.', 'agent.', 'crew.', 'campaign.')):
        return 'chain'
    return 'tool'


@contextmanager
def span(name, attributes):
    if not enabled() or name.startswith('db.'):
        yield None
        return
    parent = CURRENT.get()
    state = None
    try:
        from langsmith import RunTree
        _, destination = configuration()
        metadata = redact(attributes)
        if parent:
            tree = parent['tree'].create_child(name=name, run_type=run_type(name), inputs={}, extra={'metadata': metadata})
        else:
            tree = RunTree(name=name, run_type=run_type(name), inputs={}, extra={'metadata': metadata},
                           client=client(), **destination)
        tree.post()
        HEALTH['runs_queued'] += 1
        state = {'tree': tree, 'attributes': dict(attributes), 'outputs': {}, 'error': None}
    except Exception as exc:
        export_error(exc)
    token = CURRENT.set(state)
    try:
        yield state
    except BaseException as exc:
        if state:
            state['error'] = type(exc).__name__
        raise
    finally:
        CURRENT.reset(token)
        if state:
            try:
                tree.end(outputs=redact(state['outputs']), error=state['error'], metadata=redact(state['attributes']))
                tree.patch()
            except Exception as exc:
                export_error(exc)


def correlation():
    state = CURRENT.get()
    if not state:
        return {}
    return {'langsmith.run_id': str(state['tree'].id), 'langsmith.trace_id': str(state['tree'].trace_id)}


def event(kind, details):
    state = CURRENT.get()
    if not state:
        return
    allowed = {'agent', 'status', 'attempt', 'duration_ms', 'task_id', 'tool', 'model', 'usage', 'cost',
               'finish_reason', 'measurement_status', 'publication_id', 'remote_id', 'operation'}
    data = {key: value for key, value in details.items() if key in allowed}
    if os.getenv('TELEMETRY_CAPTURE_CONTENT', 'false').lower() == 'true':
        data.update({key: value for key, value in details.items() if key in {'decisions', 'evidence', 'summary', 'tool_input'}})
    try:
        state['tree'].add_event({'name': kind, 'kwargs': redact(data)})
        if kind == 'llm_call_finished':
            state['outputs']['usage_metadata'] = details.get('usage', {})
            state['attributes'].update(ls_model_name=details.get('model'), agent=details.get('agent'))
    except Exception as exc:
        export_error(exc)


class MirrorSpan:
    """Forward OTEL mutations while retaining outcomes when OTEL is disabled."""
    def __init__(self, wrapped, state):
        self.wrapped, self.state = wrapped, state

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def set_attribute(self, key, value):
        self.wrapped.set_attribute(key, value)
        if self.state:
            self.state['attributes'][key] = value

    def set_attributes(self, attributes):
        for key, value in attributes.items():
            self.set_attribute(key, value)

    def set_status(self, status, description=None):
        self.wrapped.set_status(status, description)
        from opentelemetry.trace import StatusCode
        if self.state and getattr(status, 'status_code', status) == StatusCode.ERROR:
            self.state['error'] = 'OperationFailed'
