"""Run offline regression checks with observability and external side effects disabled."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--terraform', action='store_true', help='Also validate and run Terraform mock-provider tests (requires init)')
    args = parser.parse_args()
    env = dict(os.environ, MODEL_ROUTING_ENABLED='false', LANGSMITH_TRACING='false', ALERTS_ENABLED='false', OPERATIONS_ENABLED='false', TELEMETRY_ENABLED='false', OTEL_SDK_DISABLED='true', DD_LLMOBS_ENABLED='0', CREWAI_TRACING_ENABLED='false',
               DD_TRACE_ENABLED='false', DD_INSTRUMENTATION_TELEMETRY_ENABLED='false',
               DD_REMOTE_CONFIGURATION_ENABLED='false',
               DD_LOGS_ENABLED='false', WORKER_ENABLED='false', PUBLISHING_ENABLED='false')
    commands = [[sys.executable,'-m','unittest','discover','-s',folder,'-v'] for folder in ('tests','crewai_agents/tests')]
    if args.terraform:
        commands.extend([['terraform','-chdir=terraform','fmt','-check','main.tf'],
                         ['terraform','-chdir=terraform','validate','-no-color'],
                         ['terraform','-chdir=terraform','test','-no-color']])
    for command in commands:
        print('CHECK', ' '.join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        if result.returncode:
            print(result.stdout); print(result.stderr, file=sys.stderr)
            return result.returncode
        # Full per-test evidence in stderr; infrastructure fixture logs in stdout can be noisy.
        print(result.stderr or result.stdout, end='')
    for source in (ROOT/'n8n').glob('*.json'):
        workflow=json.loads(source.read_text())
        print('Validated workflow JSON:',source.name,'nodes=',len(workflow['nodes']))
    print('Offline checks passed. These checks do not prove live LLM, n8n, Facebook or Datadog access.')
    return 0


if __name__ == '__main__': sys.exit(main())
