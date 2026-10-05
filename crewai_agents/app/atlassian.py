"""Deterministic Jira/Confluence publisher. Agents never receive credentials."""
import html
import json
import os
import re
from urllib.parse import quote, urlsplit

import httpx

from .observability import redact, action_span
from . import otel


def settings():
    values = {name: os.getenv(name, '').strip() for name in
              ['ATLASSIAN_EMAIL', 'ATLASSIAN_API_TOKEN']}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError('Configure ' + ', '.join(missing))
    values.update(ATLASSIAN_BASE_URL=os.getenv('ATLASSIAN_BASE_URL', 'https://bun2too.atlassian.net').rstrip('/'),
                  CONFLUENCE_BASE_URL=os.getenv('CONFLUENCE_BASE_URL', 'https://bun2too.atlassian.net').rstrip('/'),
                  JIRA_PROJECT_KEY=os.getenv('JIRA_PROJECT_KEY', 'CMA'),
                  CONFLUENCE_SPACE_KEY=os.getenv('CONFLUENCE_SPACE_KEY', 'CMA'))
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*', values['JIRA_PROJECT_KEY']):
        raise ValueError('JIRA_PROJECT_KEY is invalid')
    for name in ['ATLASSIAN_BASE_URL', 'CONFLUENCE_BASE_URL']:
        parsed = urlsplit(values[name])
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise ValueError(name + ' must be an HTTPS origin without credentials or a path')
    return values


def client(config, confluence=False):
    return httpx.Client(base_url=config['CONFLUENCE_BASE_URL' if confluence else 'ATLASSIAN_BASE_URL'],
                        auth=(config['ATLASSIAN_EMAIL'], config['ATLASSIAN_API_TOKEN']),
                        timeout=30, follow_redirects=False)


def space_id(config):
    explicit = os.getenv('CONFLUENCE_SPACE_ID', '').strip()
    if explicit:
        return explicit
    with client(config, True) as api:
        response = api.get('/wiki/api/v2/spaces', params={'keys': config['CONFLUENCE_SPACE_KEY'], 'limit': 2})
        response.raise_for_status()
        results = response.json()['results']
    if len(results) != 1 or results[0]['key'] != config['CONFLUENCE_SPACE_KEY']:
        raise ValueError('Confluence space key did not resolve uniquely')
    return str(results[0]['id'])


def queue_campaign(db, run_id):
    run = db.get(run_id)
    campaign = run.get('campaign_key', run_id)
    records = db.publications(run_id)
    existing_keys = {p['content'].get('work_key') for p in records if p['kind'] in {'story', 'task'}}
    cap = min(max(int(os.getenv('ATLASSIAN_MAX_WORK_ITEMS', '12')), 1), 30)
    # Stable identities across revisions; the campaign dossier holds all proposals,
    # including any items deferred by this hard, campaign-wide publication limit.
    db.enqueue(run_id, 'product_owner', 'epic', 'campaign', {
        'title': campaign, 'description': run['brief']['brief'],
        'acceptance_criteria': ['Review campaign objectives, deliverables and measurement plan.'],
        'owner_role': 'product_owner', 'dependencies': []})
    db.enqueue(run_id, 'delivery', 'confluence', 'dossier', {
        'campaign_key': campaign, 'run_id': run_id, 'brief': run['brief'],
        'tasks': run['tasks'], 'artifact': run['artifact']})
    seen = set()
    seen_titles = set()
    priority = {'product_owner': 0, 'engineering': 1, 'tester': 2, 'creative': 3, 'writer': 4}
    for task in sorted(run['tasks'], key=lambda task: priority.get(task['agent'], 5)):
        for item in (task.get('structured') or {}).get('work_items', []):
            item = dict(item)
            same_title = next((p for p in records if p['kind'] in {'story', 'task'} and ' '.join(p['content']['title'].casefold().split()) == ' '.join(item['title'].casefold().split())), None)
            if same_title:
                item['work_key'] = same_title['content']['work_key']
            key = item.get('work_key')
            title_key = ' '.join(item['title'].casefold().split())
            if not key or key in seen or title_key in seen_titles:
                continue
            seen.add(key)
            seen_titles.add(title_key)
            if key not in existing_keys and len(existing_keys) >= cap:
                db.event(run_id, 'backlog_item_deferred', work_key=key, reason='campaign_item_limit')
                continue
            # Existing work keys retain their issue type even if a role changes.
            previous = next((p for p in records if p['content'].get('work_key') == key), None)
            kind = previous['kind'] if previous else ('story' if task['agent'] == 'product_owner' else 'task')
            db.enqueue(run_id, task['agent'], kind, key, item)
            existing_keys.add(key)


def paragraph(text):
    return {'type': 'paragraph', 'content': [{'type': 'text', 'text': str(text)}]}


def jira_document(record, references):
    content = record['content']
    nodes = [paragraph(content.get('description', ''))]
    for title, values in [('Acceptance criteria', content.get('acceptance_criteria', [])),
                          ('Dependencies', content.get('dependencies', []))]:
        nodes.append({'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': title}]})
        nodes.extend(paragraph('• ' + str(value)) for value in values)
    nodes.append(paragraph('Responsible role: ' + content.get('owner_role', record['agent'])))
    nodes.append(paragraph('AI proposal. No sprint commitment, human approval or execution is implied.'))
    nodes.append(paragraph('Campaign: ' + record['campaign_key'] + ' | Work key: ' + content.get('work_key', 'EPIC')))
    nodes.extend(paragraph(ref['url']) for ref in references if ref.get('url'))
    document = {'type': 'doc', 'version': 1, 'content': nodes}
    if len(json.dumps(document)) > 30000:
        raise ValueError('Jira content exceeds the publication limit')
    return document


def dossier_html(record, references):
    content = record['content']
    parts = ['<h1>' + html.escape(content['campaign_key']) + '</h1>',
             '<p>AI-generated working document. Proposals are not evidence of execution.</p>',
             '<p>Run: ' + html.escape(content['run_id']) + '</p>',
             '<h2>Campaign brief</h2><p>' + html.escape(content['brief']['brief']) + '</p>']
    for reference in references:
        parts.append('<p><a href="' + html.escape(reference['url'], quote=True) + '">' + html.escape(reference.get('key', 'Related work')) + '</a></p>')
    for task in content['tasks']:
        parts.append('<h2>' + html.escape(task['agent'].replace('_', ' ').title()) + '</h2>')
        details = task.get('structured') or {'deliverable': task['output']}
        for field, value in details.items():
            parts.append('<h3>' + html.escape(field.replace('_', ' ').title()) + '</h3>')
            parts.append('<pre>' + html.escape(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)) + '</pre>')
    parts.append('<h2>Final campaign package</h2><pre>' + html.escape(json.dumps(content['artifact'], ensure_ascii=False, indent=2)) + '</pre>')
    body = ''.join(parts)
    if len(body.encode()) > 500000:
        raise ValueError('Confluence dossier exceeds 500 KB; reduce campaign scope')
    return body


def make_request(record, config, references):
    marker = 'bun2too-' + record['id']
    if record['kind'] != 'confluence':
        types = {'epic': 'Epic', 'story': 'Story', 'task': 'Task'}
        fields = {'project': {'key': config['JIRA_PROJECT_KEY']},
                  'issuetype': {'name': types[record['kind']]},
                  'summary': str(record['content']['title'])[:240],
                  'description': jira_document(record, references),
                  'labels': ['bun2too-ai', marker, 'agent-' + record['agent']]}
        if record['kind'] != 'epic':
            epic = next((ref for ref in references if ref.get('kind') == 'epic'), None)
            if not epic:
                raise ValueError('Publish the campaign Epic before its children')
            fields['parent'] = {'key': epic['key']}
        elif os.getenv('JIRA_EPIC_NAME_FIELD'):
            fields[os.environ['JIRA_EPIC_NAME_FIELD']] = fields['summary']
        return {'base': config['ATLASSIAN_BASE_URL'], 'path': '/rest/api/3/issue', 'body': {'fields': fields}}
    body = {'spaceId': space_id(config), 'status': 'current',
            'title': f"Campaign: {record['campaign_key']} [{marker}]",
            'body': {'representation': 'storage', 'value': dossier_html(record, references)}}
    if os.getenv('CONFLUENCE_PARENT_ID'):
        body['parentId'] = os.environ['CONFLUENCE_PARENT_ID']
    return {'base': config['CONFLUENCE_BASE_URL'], 'path': '/wiki/api/v2/pages', 'body': body}


def remote_link(kind, data, config):
    if kind != 'confluence':
        key = data['key']
        return {'id': data['id'], 'key': key, 'kind': kind, 'url': config['ATLASSIAN_BASE_URL'] + '/browse/' + quote(key, safe='')}
    base = os.getenv('CONFLUENCE_WEB_URL', 'https://wiki.doc.bun2too.com').rstrip('/')
    return {'id': data['id'], 'kind': kind, 'version': data.get('version', {}).get('number', 1),
            'url': base + '/wiki/pages/viewpage.action?pageId=' + quote(str(data['id']), safe='')}


class PublicationConflict(ValueError):
    pass


def find_existing(api, record, request, config):
    marker = 'bun2too-' + record['id']
    if record['kind'] == 'confluence':
        response = api.get('/wiki/api/v2/pages', params={
            'space-id': request['body']['spaceId'], 'title': request['body']['title'], 'limit': 2})
        response.raise_for_status()
        matches = response.json()['results']
    else:
        response = api.get('/rest/api/3/search/jql', params={
            'jql': 'project = "' + config['JIRA_PROJECT_KEY'] + '" AND labels = "' + marker + '"',
            'maxResults': 2, 'fields': 'summary,description'})
        response.raise_for_status()
        matches = response.json()['issues']
    if len(matches) > 1:
        raise PublicationConflict('Multiple remote records match this work key; reconcile manually')
    return remote_link(record['kind'], matches[0], config) if matches else None


@otel.observed('atlassian.publish')
def publish_one(db, key):
    config = settings()
    record = db.publication(key)
    if record['status'] == 'published':
        return record
    if record['status'] != 'pending':
        raise ValueError('Publication must be pending; reconcile unknown outcomes before retrying')
    refs = [p['remote'] for p in db.publications(record['run_id']) if p['remote']]
    request = record['request'] or make_request(record, config, refs)
    scope = (request['body']['spaceId'] if record['kind'] == 'confluence'
             else request['body']['fields']['project']['key'])
    destination = {'base': request['base'], 'scope': scope}
    current_base = config['CONFLUENCE_BASE_URL' if record['kind'] == 'confluence' else 'ATLASSIAN_BASE_URL']
    if request['base'] != current_base or (record.get('destination') and record['destination'] != destination):
        raise ValueError('Publication destination changed; restore its original configuration')
    db.update_publication(key, {'pending'}, status='sending', request=request, destination=destination, error=None)
    db.event(record['run_id'], 'atlassian_request', publication_id=key,
             operation='upsert', path=request['path'], agent=record['agent'])
    write_started = False
    try:
        with action_span(record['run_id'], 'atlassian.publish', {'publication_id': key, 'kind': record['kind'], 'path': request['path'], 'operation': 'upsert'}), client(config, record['kind'] == 'confluence') as api:
            remote = record['remote'] or find_existing(api, record, request, config)
            if remote:
                path = request['path'] + '/' + quote(str(remote['id']), safe='')
                params = {'body-format': 'storage'} if record['kind'] == 'confluence' else {'fields': 'summary,description,labels'}
                current_response = api.get(path, params=params)
                current_response.raise_for_status()
                current = current_response.json()
                if record['kind'] == 'confluence':
                    if record['remote'] and current['version']['number'] != record['remote']['version']:
                        raise PublicationConflict('Confluence was edited externally; review before replacing the dossier')
                    if not record['remote'] and current.get('body', {}).get('storage', {}).get('value') != request['body']['body']['value']:
                        raise PublicationConflict('Recovered Confluence record differs; reconcile before updating')
                    body = dict(request['body'], id=remote['id'], version={'number': current['version']['number'] + 1})
                else:
                    previous = (record.get('published_body') or request['body'])['fields']
                    if any(current['fields'].get(field) != previous.get(field) for field in ['summary', 'description']):
                        raise PublicationConflict('Jira summary/description was edited externally; review before updating')
                    # Leave human-owned status, assignee, sprint and priority untouched.
                    body = {'fields': {field: request['body']['fields'][field] for field in ['summary', 'description']}}
                write_started = True
                response = api.put(path, json=body)
                response.raise_for_status()
                data = response.json() if record['kind'] == 'confluence' else remote
            else:
                write_started = True
                response = api.post(request['path'], json=request['body'])
                response.raise_for_status()
                data = response.json()
            remote = remote_link(record['kind'], data, config)
    except PublicationConflict as exc:
        db.update_publication(key, {'sending'}, status='conflict', error=str(exc))
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        status = 'failed' if not write_started or (400 <= code < 500 and code != 408) else 'unknown'
        db.update_publication(key, {'sending'}, status=status, error=f'Atlassian HTTP {code}')
    except Exception as exc:
        db.update_publication(key, {'sending'}, status='unknown' if write_started else 'failed', error=type(exc).__name__)
    else:
        db.update_publication(key, {'sending'}, status='published', remote=remote, published_body=request['body'])
    result = db.publication(key)
    db.event(record['run_id'], 'atlassian_result', publication_id=key, status=result['status'], remote=result['remote'])
    return result


def publish_pending(db, run_id):
    for record in sorted(db.publications(run_id), key=lambda p: {'epic': 0, 'confluence': 1, 'story': 2, 'task': 3}[p['kind']]):
        if record['status'] == 'pending':
            result = publish_one(db, record['id'])
            if result['status'] != 'published':
                break
    return db.publications(run_id)


@otel.observed('atlassian.reconcile')
def reconcile(db, key, remote_id):
    """Adopt a confirmed remote object after timeout/restart; never create another."""
    record = db.publication(key)
    config = settings()
    if not record['request'] or record['request']['base'] != config['CONFLUENCE_BASE_URL' if record['kind'] == 'confluence' else 'ATLASSIAN_BASE_URL']:
        raise ValueError('Restore the original publication destination before reconciling')
    marker = 'bun2too-' + key
    with client(config, record['kind'] == 'confluence') as api:
        if record['kind'] != 'confluence':
            response = api.get('/rest/api/3/issue/' + quote(remote_id, safe=''), params={'fields': 'labels,project,summary,description'})
            response.raise_for_status()
            data = response.json()
            if any(data['fields'].get(f) != record['request']['body']['fields'].get(f) for f in ['summary', 'description']):
                raise ValueError('Remote content does not match the pending revision')
            if marker not in data['fields']['labels'] or data['fields']['project']['key'] != record['request']['body']['fields']['project']['key']:
                raise ValueError('Jira record does not match this publication')
        else:
            response = api.get('/wiki/api/v2/pages/' + quote(remote_id, safe=''), params={'body-format': 'storage'})
            response.raise_for_status()
            data = response.json()
            if data.get('body', {}).get('storage', {}).get('value') != record['request']['body']['body']['value']:
                raise ValueError('Remote content does not match the pending revision')
            if marker not in data['title'] or str(data['spaceId']) != str(record['request']['body']['spaceId']):
                raise ValueError('Confluence record does not match this publication')
    return db.update_publication(key, {'unknown', 'sending', 'failed', 'conflict'},
                                 status='published', remote=remote_link(record['kind'], data, config), published_body=record['request']['body'], error=None)


@otel.observed('retrieval.atlassian')
def load_references(brief):
    if not brief.get('jira_issue_keys') and not brief.get('confluence_page_ids'):
        return []
    config = settings()
    records = []
    with client(config) as api:
        for key in brief.get('jira_issue_keys', []):
            if not key.startswith(config['JIRA_PROJECT_KEY'] + '-'):
                raise ValueError('Referenced Jira issue must belong to configured project')
            response = api.get('/rest/api/3/issue/' + quote(key, safe=''), params={'fields': 'summary,description,status'})
            response.raise_for_status()
            records.append({'jira_key': key, 'fields': response.json()['fields']})
    with client(config, True) as api:
        for page_id in brief.get('confluence_page_ids', []):
            response = api.get('/wiki/api/v2/pages/' + quote(page_id, safe=''), params={'body-format': 'storage'})
            response.raise_for_status()
            data = response.json()
            if str(data['spaceId']) != space_id(config):
                raise ValueError('Referenced page must belong to configured space')
            records.append({'page_id': page_id, 'title': data['title'], 'body': data.get('body')})
    if len(json.dumps(records)) > 60000:
        raise ValueError('Referenced context exceeds 60000 characters; select fewer records')
    return redact(records)


def check_connection():
    config = settings()
    issue_types = []
    with client(config) as api:
        start = 0
        for _ in range(10):
            response = api.get('/rest/api/3/issue/createmeta/' + config['JIRA_PROJECT_KEY'] + '/issuetypes',
                               params={'startAt': start, 'maxResults': 50})
            response.raise_for_status()
            data = response.json()
            page = data.get('issueTypes', data.get('values', []))
            issue_types.extend(item['name'] for item in page)
            if not page or data.get('isLast', False) or start + len(page) >= data.get('total', start + len(page)):
                break
            start += len(page)
    missing = sorted({'Epic', 'Story', 'Task'} - set(issue_types))
    if missing:
        raise ValueError('Jira project must allow these issue types: ' + ', '.join(missing))
    return {'jira_project': config['JIRA_PROJECT_KEY'], 'issue_types': issue_types,
            'confluence_space_id': space_id(config), 'status': 'read_access_verified',
            'note': 'Write permissions and required custom fields are validated by actual publication responses.'}
