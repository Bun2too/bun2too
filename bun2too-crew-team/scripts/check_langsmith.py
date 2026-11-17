"""Check local LangSmith configuration; --send emits one synthetic trace only."""
import argparse
import json
import logging
from pathlib import Path
import sys
import time

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / 'crewai_agents' / '.env')

from crewai_agents.app import langsmith_trace as tracing, otel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true', help='Send and read back a synthetic trace; no LLM or publisher calls')
    args = parser.parse_args()
    # SDK errors can contain server response text; print only exception types.
    logging.getLogger('langsmith').setLevel(logging.CRITICAL)
    status = tracing.status()
    if not status['enabled'] or status.get('configuration') != 'ready':
        print(json.dumps(status))
        return 1
    if not args.send:
        print(json.dumps(status))
        return 0
    root_id = None
    try:
        with otel.span('crew-ai.langsmith.connection_check', {'diagnostic': True}):
            root_id = tracing.correlation().get('langsmith.run_id')
            with otel.span('task.trace_check', {'gen_ai.agent.name': 'diagnostic'}):
                tracing.event('diagnostic_completed', {'status': 'completed'})
        tracing.flush()
        if not root_id:
            raise RuntimeError('Trace was not created')
        error_type = None
        for attempt in range(5):
            try:
                remote = tracing.client().read_run(root_id)
                if remote.end_time:
                    print(json.dumps({'status': 'verified', 'trace_id': root_id,
                                      'destination': status['destination']}))
                    return 0
            except Exception as exc:
                error_type = type(exc).__name__
            time.sleep(1)
        print(json.dumps({'status': 'not_verified', 'trace_id': root_id, 'error_type': error_type,
                          'export_errors': tracing.HEALTH['export_errors']}))
        return 1
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
