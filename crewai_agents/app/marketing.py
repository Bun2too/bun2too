"""Deterministic marketing operations. Model output never selects credentials or destinations."""
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx


class ProfileError(ValueError):
    """Safe operator-facing profile validation message; contains no profile values."""


def profile():
    path = os.getenv('MARKETING_PROFILE_PATH') or str(Path(__file__).resolve().parents[1] / 'config' / 'marketing.json')
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, UnicodeError, ValueError):
        raise ProfileError('Marketing profile must be a readable JSON file; check MARKETING_PROFILE_PATH or packaged config/marketing.json') from None
    if not isinstance(data, dict):
        raise ProfileError('Marketing profile must be a JSON object')
    missing = [key for key in ('business_name', 'campaign_key', 'brief', 'audience', 'business_facts')
               if not isinstance(data.get(key), str) or not data[key].strip() or 'REPLACE_' in data[key]]
    if missing:
        raise ProfileError('Marketing profile has missing or placeholder fields: ' + ', '.join(missing))
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,60}', data['campaign_key']):
        raise ValueError('Invalid marketing campaign_key')
    if data.get('approval_mode', 'human') not in ('human', 'automatic'):
        raise ValueError('approval_mode must be human or automatic')
    try:
        ZoneInfo(data.get('timezone', 'America/Chicago'))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('Configure a valid IANA timezone') from None
    for key, default, low, high in [('cadence_minutes', 1440, 60, 10080), ('daily_hour', 9, 0, 23),
                                   ('daily_minute', 0, 0, 59), ('max_posts_per_day', 1, 1, 10)]:
        value = data.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'Invalid marketing profile field {key}')
        data[key] = value
    if not isinstance(data.get('source_urls', []), list) or len(data.get('source_urls', [])) > 5 or any(
            not isinstance(url, str) for url in data.get('source_urls', [])):
        raise ValueError('Configure at most five approved source URLs')
    for key in ('publish_window_start', 'publish_window_end'):
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', data.get(key, '')):
            raise ValueError('Configure ' + key + ' as HH:MM')
    if data['publish_window_start'] >= data['publish_window_end']:
        raise ValueError('Publishing window must start and end on the same local day')
    if not isinstance(data.get('forbidden_phrases', []), list) or any(
            not isinstance(p, str) or not p.strip() for p in data.get('forbidden_phrases', [])):
        raise ValueError('forbidden_phrases must contain nonempty strings')
    return data


def publication_window(config, instant=None):
    local = (instant or datetime.now(timezone.utc)).astimezone(ZoneInfo(config.get('timezone', 'America/Chicago')))
    def at(value):
        hour, minute = map(int, value.split(':'))
        return local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    start, end = at(config['publish_window_start']), at(config['publish_window_end'])
    # Stable pseudorandom choice per campaign/date: restarts and repeated ticks cannot move it.
    seed = hashlib.sha256((config['campaign_key'] + ':' + local.date().isoformat()).encode()).digest()
    from datetime import timedelta
    # Leave one polling interval before closing time; a late generation is held, never posted overnight.
    slots = max(1, int((end - start).total_seconds() // 300))
    target = start + timedelta(minutes=5 * (int.from_bytes(seed[:8], 'big') % slots))
    return target, end


def schedule_slot(config, instant=None):
    instant = instant or datetime.now(timezone.utc)
    local = instant.astimezone(ZoneInfo(config.get('timezone', 'America/Chicago')))
    anchor = local.replace(hour=config['daily_hour'], minute=config['daily_minute'], second=0, microsecond=0)
    _, end = publication_window(config, instant)
    if local > end:
        return None
    if config['cadence_minutes'] == 1440:
        return local.date().isoformat() if local >= anchor else None
    # Fixed-duration cadence, anchored in UTC. Daily cadence above follows local DST.
    bucket = int(instant.timestamp()) // (config['cadence_minutes'] * 60)
    return str(bucket)


def source_context(config):
    """Fetch only operator-configured public HTTPS URLs; never follow model-provided URLs."""
    sources = []
    for url in config.get('source_urls', []):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError('Source URLs must use public HTTPS without credentials')
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError('Source URL resolves to a private/reserved network')
        with httpx.stream('GET', url, timeout=20, follow_redirects=False,
                          headers={'User-Agent': 'bun2too-marketing-research/1.0'}) as response:
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError('Source redirects must be resolved in the operator configuration')
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 250000:
                    raise ValueError('Source exceeds size limit')
        text = content.decode('utf-8', errors='replace')
        text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', text, flags=re.S | re.I)
        text = html.unescape(re.sub(r'<[^>]+>', ' ', text))
        text = re.sub(r'\s+', ' ', text)[:8000]
        sources.append({'url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'text': text})
    return sources


def check_artifact(run, config=None):
    artifact = run['artifact']
    if artifact.get('blockers'):
        raise ValueError('Artifact has unresolved blockers')
    if len(artifact['posts']) != 1 or artifact['posts'][0]['channel'].lower() != 'facebook':
        raise ValueError('Scheduled MVP requires exactly one Facebook post')
    if len(artifact['posts'][0]['text']) > 5000:
        raise ValueError('Facebook copy exceeds configured MVP limit')
    articles = artifact.get('articles', [])
    if len(articles) != 1:
        raise ValueError('Scheduled MVP requires exactly one article')
    allowed = {source['url'] for source in run.get('source_snapshots', [])}
    if any(url not in allowed for url in articles[0].get('source_urls', [])):
        raise ValueError('Article cites a source that was not retrieved')
    if config:
        reviews = {task['agent']: task.get('structured') or {} for task in run.get('tasks', [])}
        if any(reviews.get(role, {}).get('approved_for_publication') is not True for role in ('tester', 'editor')):
            raise ValueError('Tester and Editor must both approve publication')
        copy = articles[0]['title'] + '\n' + articles[0]['body'] + '\n' + artifact['posts'][0]['text']
        if any(phrase.casefold() in copy.casefold() for phrase in config.get('forbidden_phrases', [])):
            raise ValueError('Content contains a prohibited phrase')
        if re.search(r'https?://|www\.', copy, re.I):
            raise ValueError('Keep URLs in source_urls; the publisher adds the approved article link')
    return artifact


def graph_config():
    version = os.getenv('FACEBOOK_GRAPH_VERSION', '')
    page = os.getenv('FACEBOOK_PAGE_ID', '')
    token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN', '')
    if not re.fullmatch(r'v\d+\.\d+', version) or not re.fullmatch(r'\d+', page) or not token:
        raise ValueError('Configure FACEBOOK_GRAPH_VERSION, FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN')
    return version, page, token


def delivery_config():
    """Require a configured delivery destination before unattended model spending."""
    if os.getenv('PUBLISHING_ENABLED', 'false').lower() != 'true':
        raise ValueError('Publishing is disabled')
    version, page, token = graph_config()
    base = os.getenv('PUBLIC_API_BASE_URL', '').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('PUBLIC_API_BASE_URL must be the deployed HTTPS CrewAI URL')
    return version, page, token, base


def publish_one(db, run_id):
    version, page, token, base = delivery_config()
    config = profile()
    run = db.get(run_id)
    artifact = check_artifact(run, config)
    if run['status'] != 'approved' or not run.get('approval'):
        raise ValueError('Run must be approved before publication')
    digest = hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()
    if digest != run['approval']['sha256']:
        raise ValueError('Approved content hash does not match')
    instant = datetime.now(timezone.utc)
    if run.get('scheduled'):
        if not run.get('publish_after') or not run.get('publish_before'):
            raise ValueError('Run has no persisted publishing window')
        if instant < datetime.fromisoformat(run['publish_after']):
            raise ValueError('Publication is not due yet')
        if instant > datetime.fromisoformat(run['publish_before']):
            db.update(run_id, expected={'approved'}, status='expired')
            db.event(run_id, 'publication_expired')
            raise ValueError('Publication window has expired; do not publish stale content')
    day = datetime.now(ZoneInfo(config.get('timezone', 'America/Chicago'))).date().isoformat()
    publication = db.claim_social(run_id, page, day, config['max_posts_per_day'])
    if not publication['acquired']:
        return publication
    # Claim is committed before POST. An ambiguous outcome is never automatically retried.
    db.event(run_id, 'facebook_publish_started', publication_id=publication['id'], page_id=page)
    try:
        response = httpx.post(f'https://graph.facebook.com/{version}/{page}/feed',
                              headers={'Authorization': 'Bearer ' + token},
                              data={'message': artifact['posts'][0]['text'], 'link': base + '/articles/' + run_id},
                              timeout=30, follow_redirects=False)
        if response.status_code >= 400 and response.status_code < 500:
            result = db.finish_social(publication['id'], 'failed', error=f'Facebook HTTP {response.status_code}')
        else:
            response.raise_for_status()
            remote = response.json().get('id', '')
            if not isinstance(remote, str) or not re.fullmatch(r'\d+_\d+', remote):
                raise ValueError('Unexpected Facebook post ID')
            result = db.finish_social(publication['id'], 'published', remote_id=remote)
    except Exception as exc:
        result = db.finish_social(publication['id'], 'unknown', error=type(exc).__name__)
    db.event(run_id, 'facebook_publish_finished', publication_id=result['id'],
             status=result['status'], remote_id=result.get('remote_id'))
    return result


def collect_metrics(db):
    version, page, token = graph_config()
    collected = []
    for publication in db.social_recent():
        remote = publication.get('remote_id')
        if publication['status'] != 'published' or publication['page_id'] != page or not remote:
            continue
        try:
            response = httpx.get(f'https://graph.facebook.com/{version}/{remote}',
                                 params={'fields': 'id,shares,comments.limit(0).summary(true),reactions.limit(0).summary(true)'},
                                 headers={'Authorization': 'Bearer ' + token}, timeout=20)
            response.raise_for_status()
            data = response.json()
            metrics = {}
            for name in ('comments', 'reactions'):
                value = (data.get(name) or {}).get('summary', {}).get('total_count')
                if type(value) is int and value >= 0:
                    metrics[name] = value
            shares = (data.get('shares') or {}).get('count')
            if type(shares) is int and shares >= 0:
                metrics['shares'] = shares
            db.social_metrics(publication['id'], metrics)
            db.event(publication['run_id'], 'facebook_metrics_collected', metrics=metrics)
            collected.append({'publication_id': publication['id'], 'metrics': metrics})
        except Exception as exc:
            db.event(publication['run_id'], 'facebook_metrics_failed', error_type=type(exc).__name__)
    return collected
