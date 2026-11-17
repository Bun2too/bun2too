import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from crewai_agents.app import atlassian
from crewai_agents.app.observability import redact
from crewai_agents.app.store import Store


class TrackingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Store(Path(temp.name) / 'runs.db')
        env = patch.dict(os.environ, {'ATLASSIAN_EMAIL': 'bot@example.com',
            'ATLASSIAN_API_TOKEN': 'test-secret-token', 'ATLASSIAN_BASE_URL': 'https://bun2too.atlassian.net',
            'CONFLUENCE_BASE_URL': 'https://bun2too.atlassian.net', 'CONFLUENCE_SPACE_ID': '123',
            'JIRA_PROJECT_KEY': 'CMA', 'ATLASSIAN_MAX_WORK_ITEMS': '12',
            'ATLASSIAN_MAX_NEW_CAMPAIGNS_PER_DAY': '3', 'DD_LLMOBS_ENABLED': '0'})
        env.start()
        self.addCleanup(env.stop)
        self.posts = []
        self.puts = []
        self.remote = {}
        self.failure = None
        transport = httpx.MockTransport(self.respond)
        mock = patch.object(atlassian, 'client', side_effect=lambda *args: httpx.Client(
            base_url='https://bun2too.atlassian.net', transport=transport))
        mock.start()
        self.addCleanup(mock.stop)

    def respond(self, request):
        path = request.url.path
        if request.method == 'GET' and path.endswith('/search/jql'):
            return httpx.Response(200, json={'issues': []})
        if request.method == 'GET' and path == '/wiki/api/v2/pages':
            return httpx.Response(200, json={'results': []})
        if request.method == 'GET':
            return httpx.Response(200, json=self.remote[path])
        if self.failure:
            if isinstance(self.failure, Exception):
                raise self.failure
            return httpx.Response(self.failure, json={})
        body = json.loads(request.content)
        if request.method == 'POST':
            self.posts.append((path, body))
            number = str(len(self.posts))
            if path == '/rest/api/3/issue':
                data = {'id': number, 'key': 'CMA-' + number, 'fields': body['fields']}
            else:
                data = dict(body, id=number, version={'number': 1}, body={'storage': body['body']})
            self.remote[path + '/' + number] = data
            return httpx.Response(201 if 'issue' in path else 200, json=data)
        self.puts.append((path, body))
        if '/issue/' in path:
            self.remote[path]['fields'].update(body['fields'])
            return httpx.Response(204)
        self.remote[path] = dict(body, body={'storage': body['body']})
        return httpx.Response(200, json=self.remote[path])

    def campaign(self, key='launch', description='Create approved draft', count=1):
        run = self.db.create({'campaign_key': key, 'brief': 'Launch campaign'})
        items = [{'work_key': f'STORY-{index:03}', 'title': f'Launch story {index}',
                  'description': description, 'owner_role': 'writer',
                  'acceptance_criteria': ['Review factual claims'], 'dependencies': []}
                 for index in range(count)]
        self.db.update(run['id'], status='awaiting_review', artifact={'campaign_plan': 'plan'},
                       tasks=[{'agent': 'product_owner', 'output': 'draft', 'structured': {'work_items': items}}])
        atlassian.queue_campaign(self.db, run['id'])
        return run['id']

    def test_hierarchy_and_repeated_publish(self):
        run = self.campaign()
        result = atlassian.publish_pending(self.db, run)
        self.assertTrue(all(p['status'] == 'published' for p in result))
        issues = [body for path, body in self.posts if path.endswith('/issue')]
        self.assertEqual([item['fields']['issuetype']['name'] for item in issues], ['Epic', 'Story'])
        self.assertEqual(issues[1]['fields']['parent'], {'key': 'CMA-1'})
        self.assertEqual(len(self.posts), 3)
        atlassian.queue_campaign(self.db, run)
        atlassian.publish_pending(self.db, run)
        self.assertEqual(len(self.posts), 3)

    def test_campaign_revision_updates_dossier_without_duplicate_tickets(self):
        atlassian.publish_pending(self.db, self.campaign())
        new_run = self.campaign()
        atlassian.publish_pending(self.db, new_run)
        self.assertEqual(len(self.posts), 3)
        self.assertEqual(len(self.puts), 1)
        self.assertIn('/pages/', self.puts[0][0])

    def test_human_edit_blocks_overwrite(self):
        first = self.campaign()
        atlassian.publish_pending(self.db, first)
        story = next(p for p in self.db.publications(first) if p['kind'] == 'story')
        self.remote['/rest/api/3/issue/' + story['remote']['id']]['fields']['summary'] = 'Human edited'
        new_run = self.campaign(description='Revised requirement')
        results = atlassian.publish_pending(self.db, new_run)
        self.assertEqual(next(p for p in results if p['kind'] == 'story')['status'], 'conflict')
        self.assertFalse(any('/issue/' in path for path, _ in self.puts))

    def test_timeout_cannot_create_duplicate_on_retry(self):
        run = self.campaign()
        self.failure = httpx.ReadTimeout('ambiguous')
        atlassian.publish_pending(self.db, run)
        record = self.db.publications(run)[0]
        self.assertEqual(record['status'], 'unknown')
        with self.assertRaises(ValueError):
            atlassian.publish_one(self.db, record['id'])

    def test_definite_rejection_is_recorded(self):
        run = self.campaign()
        self.failure = 401
        atlassian.publish_pending(self.db, run)
        self.assertEqual(self.db.publications(run)[0]['status'], 'failed')

    def test_campaign_and_daily_limits(self):
        with patch.dict(os.environ, {'ATLASSIAN_MAX_WORK_ITEMS': '2'}):
            run = self.campaign(count=5)
        self.assertEqual(len(self.db.publications(run)), 4)
        self.assertEqual(sum(e['kind'] == 'backlog_item_deferred' for e in self.db.events(run)), 3)
        self.campaign('second')
        self.campaign('third')
        with self.assertRaisesRegex(ValueError, 'Daily'):
            self.campaign('fourth')

    def test_same_campaign_cannot_run_concurrently(self):
        self.db.create({'campaign_key': 'active'})
        with self.assertRaisesRegex(ValueError, 'active run'):
            self.db.create({'campaign_key': 'active'})

    def test_redaction_and_persistence(self):
        run = self.campaign()
        self.db.event(run, 'tool', api_key='test-secret-token', input='Bearer test-secret-token')
        events = Store(self.db.path).events(run)
        self.assertNotIn('test-secret-token', json.dumps(events))
        self.assertEqual(redact({'authorization': 'value'})['authorization'], '[REDACTED]')


if __name__ == '__main__':
    unittest.main()


class ScheduledTrackingTests(unittest.TestCase):
    setUp = TrackingTests.setUp
    respond = TrackingTests.respond

    def test_daily_runs_have_distinct_stories_and_dossiers(self):
        ids = []
        for day in ('2026-10-12', '2026-10-13'):
            run, _ = self.db.schedule(day, {'campaign_key': 'daily', 'brief': 'AI engineering'})
            self.db.update(run['id'], tasks=[{'agent': 'writer', 'output': 'Draft',
                'structured': {'decisions': ['Use evidence'], 'evidence': ['Source']}}])
            atlassian.queue_scheduled(self.db, run['id'])
            atlassian.publish_pending(self.db, run['id'])
            records = self.db.publications(run['id'])
            self.assertEqual(len(records), 4)
            self.assertEqual(sum(p['kind'] == 'story' for p in records), 2)
            ids.append({p['id'] for p in records})
            before = len(self.posts)
            atlassian.queue_scheduled(self.db, run['id'])
            atlassian.publish_pending(self.db, run['id'])
            self.assertEqual(len(self.posts), before)
        self.assertFalse(ids[0] & ids[1])

    def test_publication_story_updates_same_issue_with_remote_outcome(self):
        run, _ = self.db.schedule('today', {'campaign_key': 'daily', 'brief': 'AI'})
        atlassian.queue_scheduled(self.db, run['id'])
        atlassian.publish_pending(self.db, run['id'])
        story = next(p for p in self.db.publications(run['id']) if p['content'].get('work_key') == 'PUBLISH')
        self.db.update(run['id'], status='approved')
        publication = self.db.claim_social(run['id'], '123', '2026-10-13', 1)
        self.db.finish_social(publication['id'], 'published', remote_id='123_456')
        atlassian.queue_scheduled(self.db, run['id'])
        atlassian.publish_pending(self.db, run['id'])
        updated = self.db.publication(story['id'])
        self.assertEqual(updated['remote']['id'], story['remote']['id'])
        self.assertIn('123_456', updated['content']['description'])
        self.assertEqual(updated['status'], 'published')
        self.assertEqual(len(self.posts), 3)

    def test_agent_report_preserves_unknown_measurements_and_failure(self):
        run = self.db.create({'brief': 'test'})['id']
        self.db.event(run, 'agent_finished', agent='writer', status='failed', duration_ms=500)
        self.db.event(run, 'llm_call_finished', agent='writer', usage={'input_tokens': 100},
                      cost={'status': 'unavailable'})
        report = {row['agent']: row for row in atlassian.agent_report(self.db, run)}
        self.assertEqual(report['writer']['failures'], 1)
        self.assertEqual(report['writer']['usage'], {'input_tokens': 100})
        self.assertIsNone(report['writer']['estimated_cost_usd'])
        self.assertEqual(report['tester']['status'], 'not_started')
        self.assertIsNone(report['tester']['duration_ms'])

    def test_sync_outage_does_not_change_run_state(self):
        run, _ = self.db.schedule('today', {'campaign_key': 'daily', 'brief': 'AI'})
        self.db.update(run['id'], status='dispatched')
        with patch.object(atlassian, 'publish_pending', side_effect=httpx.ConnectError('offline')):
            atlassian.sync_scheduled(self.db, run['id'])
        self.assertEqual(self.db.get(run['id'])['status'], 'dispatched')
        self.assertEqual(self.db.events(run['id'])[-1]['kind'], 'atlassian_sync_failed')
