"""Trace CI commands without dumping their environment or enabling shell tracing.

Only pass non-secret arguments. Credentials must be supplied through environment
variables. Command output streams directly to GitHub's normal masked step logs.
"""
import datetime
import json
import os
import shlex
import subprocess
import sys
import time


def run(argv):
    if not argv:
        raise ValueError('A command is required')
    command = shlex.join(argv)
    # Defensive redaction for accidentally supplied known deployment secrets.
    for key, value in os.environ.items():
        if value and any(marker in key.upper() for marker in ('TOKEN', 'PASSWORD', 'SECRET')):
            command = command.replace(value, '[REDACTED]')
    start = time.monotonic()
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f'[{stamp}] START command={json.dumps(command)} cwd={json.dumps(os.getcwd())}', flush=True, file=sys.stderr)
    try:
        result = subprocess.run(argv, check=False)
        code = result.returncode if result.returncode >= 0 else 128 - result.returncode
    except OSError as exc:
        print(f'Command could not start: {type(exc).__name__}', flush=True, file=sys.stderr)
        code = 127
    elapsed = time.monotonic() - start
    print(f'END command={json.dumps(command)} exit_code={code} duration_seconds={elapsed:.3f}', flush=True, file=sys.stderr)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        try:
            with open(summary, 'a') as stream:
                # Fixed executable names only; no command arguments in Markdown.
                executable = os.path.basename(argv[0])
                name = executable if executable in ('python3', 'terraform', 'node', 'npm', 'railway', 'git') else 'command'
                stream.write(f'- `{name}`: exit **{code}**, {elapsed:.3f}s. See step log for command.\n')
        except OSError:
            print('Could not append command result to job summary.', flush=True, file=sys.stderr)
    return code


if __name__ == '__main__':
    sys.exit(run(sys.argv[1:]))
