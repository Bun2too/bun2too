"""Deterministic marketing operations. Model output never selects credentials or destinations."""
import base64
import binascii
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import time
import xml.etree.ElementTree as ET
from functools import lru_cache
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from .observability import error_details


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
    if not isinstance(data.get('research_feeds', []), list) or not data.get('research_feeds') or len(data['research_feeds']) > 8 or any(
            not isinstance(url, str) for url in data['research_feeds']):
        raise ValueError('Configure one to eight public HTTPS research_feeds')
    for key, default, low, high in [('research_max_age_days', 14, 1, 90), ('research_item_limit', 8, 3, 20)]:
        value = data.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'Invalid marketing profile field {key}')
        data[key] = value
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


def _public_https(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Research URLs must use public HTTPS without credentials')
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Research URL resolves to a private/reserved network')


def _download(url, limit):
    _public_https(url)
    with httpx.stream('GET', url, timeout=25, follow_redirects=False,
                      headers={'User-Agent': 'bun2too-marketing-research/1.0'}) as response:
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError('Research redirects must be resolved in the operator configuration')
        content = bytearray()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > limit:
                raise ValueError('Research source exceeds size limit')
    return bytes(content)


def _plain_text(value, limit=8000):
    value = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', value or '', flags=re.S | re.I)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', value))).strip()[:limit]


def _date(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _feed_items(feed_url, retrieved_at):
    """Return recent RSS/Atom entries as bounded, untrusted evidence records."""
    try:
        root = ET.fromstring(_download(feed_url, 750000))
    except ET.ParseError:
        raise ValueError('Research feed is not valid XML') from None
    records = []
    for item in root.iter():
        if item.tag.rsplit('}', 1)[-1] not in {'item', 'entry'}:
            continue
        values, links = {}, []
        for child in item:
            name = child.tag.rsplit('}', 1)[-1]
            if name == 'link':
                link = child.attrib.get('href') or (child.text or '').strip()
                if link and child.attrib.get('rel', 'alternate') in {'alternate', ''}:
                    links.append(link)
            elif name in {'title', 'description', 'summary', 'content', 'pubDate', 'published', 'updated'}:
                values.setdefault(name, ''.join(child.itertext()))
        published = _date(values.get('pubDate') or values.get('published') or values.get('updated'))
        url = next((link for link in links if link.startswith('https://')), '')
        title = _plain_text(values.get('title'), 300)
        summary = _plain_text(values.get('content') or values.get('description') or values.get('summary'))
        if url and title and summary:
            _public_https(url)
            records.append({'url': url, 'feed_url': feed_url, 'title': title,
                            'published_at': published.isoformat() if published else None,
                            'retrieved_at': retrieved_at.isoformat(), 'text': summary})
    return records


def source_context(config, instant=None):
    """Gather current topics from configured feeds plus optional evergreen references."""
    retrieved_at = instant or datetime.now(timezone.utc)
    cutoff = retrieved_at.timestamp() - config.get('research_max_age_days', 14) * 86400
    recent = []
    failures = []
    for feed_url in config.get('research_feeds', []):
        try:
            recent.extend(item for item in _feed_items(feed_url, retrieved_at)
                          if item['published_at'] and datetime.fromisoformat(item['published_at']).timestamp() >= cutoff)
        except (ValueError, OSError, httpx.HTTPError) as exc:
            failures.append({'feed_url': feed_url, 'error_type': type(exc).__name__})
    recent.sort(key=lambda item: item['published_at'], reverse=True)
    # Keep source diversity before filling remaining slots by recency.
    selected, seen_feeds, seen_urls = [], set(), set()
    for item in recent:
        if item['feed_url'] not in seen_feeds:
            selected.append(item); seen_feeds.add(item['feed_url']); seen_urls.add(item['url'])
    for item in recent:
        if item['url'] not in seen_urls:
            selected.append(item); seen_urls.add(item['url'])
    selected = selected[:config.get('research_item_limit', 8)]
    if not selected:
        raise ValueError('No recent research items were available from configured feeds')
    for url in config.get('source_urls', []):
        selected.append({'url': url, 'feed_url': None, 'title': 'Evergreen reference',
                         'published_at': None, 'retrieved_at': retrieved_at.isoformat(),
                         'text': _plain_text(_download(url, 250000).decode('utf-8', errors='replace'))})
    return selected, failures


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


def artwork_settings():
    enabled = os.getenv('ARTICLE_ARTWORK_ENABLED', 'true').lower() in {'true', '1'}
    if not enabled:
        return None
    model = os.getenv('ARTICLE_IMAGE_MODEL', 'gpt-image-2.5-flare')
    quality = os.getenv('ARTICLE_IMAGE_QUALITY', 'medium')
    size = os.getenv('ARTICLE_IMAGE_SIZE', '1536x1024')
    if not re.fullmatch(r'gpt-image-[A-Za-z0-9._-]+', model):
        raise ValueError('ARTICLE_IMAGE_MODEL must be a GPT Image model')
    if quality not in {'low', 'medium', 'high'}:
        raise ValueError('ARTICLE_IMAGE_QUALITY must be low, medium, or high')
    if size not in {'1024x1024', '1536x1024', '1024x1536'}:
        raise ValueError('ARTICLE_IMAGE_SIZE is not supported by the article layout')
    try:
        timeout = int(os.getenv('ARTICLE_IMAGE_TIMEOUT_SECONDS', '240'))
    except ValueError:
        raise ValueError('ARTICLE_IMAGE_TIMEOUT_SECONDS must be an integer') from None
    if not 30 <= timeout <= 600:
        raise ValueError('ARTICLE_IMAGE_TIMEOUT_SECONDS must be between 30 and 600')
    return {'model': model, 'quality': quality, 'size': size, 'timeout_seconds': timeout}


def generate_article_artwork(data_dir, run_id, artifact):
    """Generate one bounded editorial hero and persist it on the mounted volume."""
    settings = artwork_settings()
    if settings is None:
        return {'status': 'disabled'}
    key = os.getenv('OPENAI_API_KEY', '')
    if not key:
        raise ValueError('OPENAI_API_KEY is required when article artwork is enabled')
    article = artifact['articles'][0]
    title = re.sub(r'\s+', ' ', article['title']).strip()[:200]
    prompt = ('Create a sophisticated editorial hero illustration for a technology magazine article titled: "' + title + '". '
              'Use a bold contemporary composition, layered geometric forms, tactile texture, dramatic but refined lighting, '
              'and a restrained palette with one vivid orange accent. Convey the topic through visual metaphor. '
              'Landscape 3:2 composition with a clear focal point and generous negative space. '
              'No words, letters, numbers, logos, trademarks, watermarks, UI screenshots, identifiable people, or photorealistic faces.')
    from openai import OpenAI
    response = OpenAI(api_key=key, timeout=settings['timeout_seconds'], max_retries=0).images.generate(
        model=settings['model'], prompt=prompt, size=settings['size'], quality=settings['quality'],
        output_format='webp', output_compression=82, n=1)
    encoded = response.data[0].b64_json if response.data else None
    if not encoded:
        raise ValueError('Image API returned no artwork data')
    try:
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('Image API returned invalid base64 artwork') from None
    if not 100 <= len(image) <= 20_000_000 or image[:4] != b'RIFF' or image[8:12] != b'WEBP':
        raise ValueError('Image API returned an invalid or oversized WebP')
    asset_dir = Path(data_dir) / 'article-assets'
    asset_dir.mkdir(parents=True, exist_ok=True)
    filename = run_id + '.webp'
    temporary = asset_dir / (filename + '.tmp')
    temporary.write_bytes(image)
    temporary.chmod(0o644)
    temporary.replace(asset_dir / filename)
    return {'status': 'ready', 'filename': filename, 'format': 'webp',
            'alt': 'Editorial illustration for ' + title,
            'model': settings['model'], 'quality': settings['quality'], 'size': settings['size']}


def artwork_path(data_dir, metadata):
    filename = (metadata or {}).get('filename', '')
    if (metadata or {}).get('status') != 'ready' or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}\.webp', filename):
        return None
    path = Path(data_dir) / 'article-assets' / filename
    return path if path.is_file() else None


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


@lru_cache(maxsize=4)
def _facebook_destination(version, page, configured_token, time_bucket):
    """Read-only checks; returned credentials stay in process memory only."""
    base = f'https://graph.facebook.com/{version}'
    def get(path, token, **params):
        response = httpx.get(base + path, headers={'Authorization': 'Bearer ' + token},
                             params=params, timeout=20, follow_redirects=False)
        response.raise_for_status()
        return response.json()
    identity = get('/me', configured_token, fields='id,name')
    page_token = configured_token
    if identity.get('id') != page:
        # A user token with existing Page management grants can obtain the token
        # for this exact configured Page. Never choose the first managed Page.
        selected = get('/' + page, configured_token, fields='id,access_token')
        if selected.get('id') != page or not selected.get('access_token'):
            raise ValueError('The configured Facebook credential cannot obtain the target Page token')
        page_token = selected['access_token']
        identity = get('/me', page_token, fields='id,name')
    if identity.get('id') != page:
        raise ValueError('Facebook token identity does not match FACEBOOK_PAGE_ID')
    # /feed includes content by other users and can require permissions beyond
    # this publisher. Validate the Page's own posts, which is what we manage.
    get('/' + page + '/posts', page_token, fields='id', limit=1)
    return page_token, identity.get('name', '')


def facebook_destination():
    version, page, token = graph_config()
    page_token, name = _facebook_destination(version, page, token, int(time.time() // 300))
    return version, page, page_token, name


def verify_delivery():
    delivery_config()
    _, page, _, name = facebook_destination()
    return {'status': 'ready', 'page_id': page, 'page_name': name,
            'checks': ['page_identity', 'page_posts_read'], 'publishing_permission_verified': False}


def publish_one(db, run_id):
    version, page, token, base = delivery_config()
    version, page, token, _ = facebook_destination()
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
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                diagnostic = error_details(exc)
            result = db.finish_social(publication['id'], 'failed', error=f'Facebook HTTP {response.status_code}',
                                      error_details=diagnostic)
        else:
            response.raise_for_status()
            remote = response.json().get('id', '')
            if not isinstance(remote, str) or not re.fullmatch(r'\d+_\d+', remote):
                raise ValueError('Unexpected Facebook post ID')
            result = db.finish_social(publication['id'], 'published', remote_id=remote)
    except Exception as exc:
        result = db.finish_social(publication['id'], 'unknown', error=type(exc).__name__, error_details=error_details(exc))
    db.event(run_id, 'facebook_publish_finished', publication_id=result['id'],
             status=result['status'], remote_id=result.get('remote_id'), page_id=page,
             operation='facebook.publish', error=result.get('error_details'), reason=result.get('error'))
    return result


def collect_metrics(db):
    version, page, token, _ = facebook_destination()
    collected = []
    for publication in db.social_recent():
        remote = publication.get('remote_id')
        if publication['status'] != 'published' or publication['page_id'] != page or not remote:
            continue
        metrics, unavailable, successful_requests = {}, {}, 0
        fields = {'shares': 'shares', 'comments': 'comments.limit(0).summary(true)',
                  'reactions': 'reactions.limit(0).summary(true)'}
        for name, field in fields.items():
            try:
                response = httpx.get(f'https://graph.facebook.com/{version}/{remote}',
                                     params={'fields': 'id,' + field},
                                     headers={'Authorization': 'Bearer ' + token}, timeout=20,
                                     follow_redirects=False)
                response.raise_for_status()
                successful_requests += 1
                data = response.json().get(name) or {}
                value = data.get('count') if name == 'shares' else data.get('summary', {}).get('total_count')
                if type(value) is int and value >= 0:
                    metrics[name] = value
                else:
                    unavailable[name] = {'message': 'Facebook did not return this count'}
            except Exception as exc:
                unavailable[name] = error_details(exc)
        status = 'failed' if not successful_requests else ('partial' if unavailable else 'completed')
        # A missing or unauthorized count is never zero. Persist permitted counts
        # independently so one restricted field cannot discard all observations.
        if successful_requests:
            db.social_metrics(publication['id'], metrics, unavailable=unavailable)
        reason = 'Unavailable Facebook metrics: ' + ', '.join(unavailable) if unavailable else None
        kind = 'facebook_metrics_failed' if status == 'failed' else ('facebook_metrics_partial' if unavailable else 'facebook_metrics_collected')
        db.event(publication['run_id'], kind, status=status, metrics=metrics, reason=reason,
                 missing_metrics=unavailable, error=next(iter(unavailable.values()), None) if status == 'failed' else None,
                 publication_id=publication['id'], remote_id=remote, operation='facebook.metrics')
        collected.append({'publication_id': publication['id'], 'run_id': publication['run_id'],
                          'status': status, 'metrics': metrics, 'missing_metrics': unavailable, 'reason': reason})
    return collected
