"""Classify provider failures before deciding whether another attempt is safe."""
import random


def classify(diagnostic, attempt=1):
    causes = diagnostic.get('causes') or [diagnostic]
    codes = {str(c.get(key, '')).lower() for c in causes for key in ('provider_code', 'provider_type')}
    statuses = {str(c.get('status_code', '')) for c in causes}
    kinds = {c.get('type', c.get('kind')) for c in causes}
    if codes & {'insufficient_quota', 'credit_balance_exhausted', 'billing_hard_limit_reached', 'billing_not_active'}:
        return dict(category='provider_billing', retryable=False, pause_generation=True,
                    reason='AI provider credits or quota exhausted; restore billing, then resume generation.', delay_seconds=None)
    if statuses & {'401', '403'} or kinds & {'AuthenticationError', 'PermissionDeniedError'}:
        return dict(category='provider_authentication', retryable=False, pause_generation=True,
                    reason='Provider authentication or permission denied; repair credentials/access, then resume generation.', delay_seconds=None)
    transient = statuses & {'408', '429', '500', '502', '503', '504'} or kinds & {
        'TimeoutError', 'ReadTimeout', 'ConnectTimeout', 'APITimeoutError', 'APIConnectionError', 'ConnectError', 'RemoteProtocolError'}
    if transient:
        delay = min(600, 60 * 2 ** min(max(attempt - 1, 0), 3)) + random.randint(0, 30)
        delay = max(delay, max((c.get('retry_after_seconds', 0) for c in causes), default=0))
        return dict(category='transient_provider', retryable=True, pause_generation=False,
                    reason='Temporary provider/network failure; bounded recovery will retry within the publishing window.', delay_seconds=delay)
    return dict(category='generation_error', retryable=False, pause_generation=False,
                reason='Generation failed; inspect the recorded exception and repair the cause before retrying.', delay_seconds=None)
