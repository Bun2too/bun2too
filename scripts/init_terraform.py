"""Retry only transient provider-download failures; retain locked verification."""
import re
import subprocess
import sys
import time

COMMAND = ['terraform', 'init', '-input=false', '-no-color', '-lockfile=readonly']
DELAYS = (5, 15)  # Three total attempts, not an unbounded retry loop.


def transient_provider_failure(output):
    errors = re.split(r'(?m)^Error: ', output)[1:]
    if not errors:
        return False
    permanent = ('checksum', 'signature verification failed', 'invalid signature',
                 'authentication', 'unauthorized', 'forbidden', '401', '403',
                 'certificate', 'inconsistent dependency lock', 'no available releases')
    transient = ('502 bad gateway', '503 service unavailable', '504 gateway timeout',
                 '429 too many requests', 'connection reset', 'connection refused',
                 'temporary failure in name resolution', 'i/o timeout', 'tls handshake timeout',
                 'context deadline exceeded', 'client.timeout exceeded')
    return all(('failed to install provider' in error.lower()
                or 'failed to query available provider packages' in error.lower())
               and not any(marker in error.lower() for marker in permanent)
               and any(marker in error.lower() for marker in transient)
               for error in errors)


def initialize(run=subprocess.run, sleep=time.sleep):
    for attempt in range(1, 4):
        print(f'Terraform initialization attempt {attempt}/3 (locked provider checks enabled).', flush=True)
        try:
            result = run(COMMAND, check=False, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            # No re-entry while an unexpectedly hung initialization may have child processes.
            print('::error::Terraform initialization exceeded 120 seconds; inspect runner/network health. No apply attempted.', flush=True)
            return 124
        except OSError:
            print('::error::Could not start Terraform; verify CLI installation.', flush=True)
            return 127
        print(result.stdout or '', end='', flush=True)  # Normal masked CI command output.
        if result.returncode == 0:
            return 0
        if not transient_provider_failure(result.stdout or ''):
            return result.returncode
        if attempt == 3:
            print('::error::Provider download failed after three initialization attempts. '
                  'No plan/apply attempted. Check GitHub release/registry availability and rerun '
                  'the updated workflow after recovery; do not change credentials or disable verification.', flush=True)
            return result.returncode
        delay = DELAYS[attempt - 1]
        print(f'::warning::Transient provider download failure; retrying initialization in {delay} seconds.', flush=True)
        sleep(delay)
    return 1


if __name__ == '__main__':
    sys.exit(initialize())
