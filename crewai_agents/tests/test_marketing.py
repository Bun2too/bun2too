import base64
import hashlib
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import httpx
from fastapi.testclient import TestClient
from crewai_agents.app import main, marketing, telemetry
from crewai_agents.app.models import MarketingArtifact
from crewai_agents.app.store import Store


def config():
    return dict(business_name='Bun2too', campaign_key='bun2too-daily', brief='Help our audience',
                business_facts='Verified facts', audience='Business owners', timezone='America/Chicago',
                daily_hour=8, daily_minute=0, cadence_minutes=1440, max_posts_per_day=1,
                publish_window_start='08:00', publish_window_end='22:30', approval_mode='automatic', source_urls=[],
                research_feeds=['https://news.example/feed'], research_max_age_days=14, research_item_limit=8)


def artifact():
    return MarketingArtifact(campaign_plan='Plan', requirements='Evidence', creative_brief='Concept',
        engineering_plan='No code execution', delivery_plan='One post', measurement_plan='Observed engagement',
        articles=[dict(title='Useful article', body='Verified business information. ' * 8)],
        posts=[dict(channel='facebook', text='Read our useful article.')]).model_dump()


class ProfileConfigurationTests(unittest.TestCase):
    def test_placeholder_diagnostics_identify_both_fields_without_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'marketing.json'
            data = dict(config(), audience='REPLACE_PRIVATE_AUDIENCE', business_facts='REPLACE_PRIVATE_FACTS')
            path.write_text(json.dumps(data))
            with patch.dict(os.environ, MARKETING_PROFILE_PATH=str(path)), self.assertRaises(marketing.ProfileError) as caught:
                marketing.profile()
            message = str(caught.exception)
            self.assertIn('audience', message)
            self.assertIn('business_facts', message)
            self.assertNotIn('PRIVATE', message)
            path.write_text(json.dumps(config()))
            with patch.dict(os.environ, MARKETING_PROFILE_PATH=str(path)):
                self.assertEqual(marketing.profile()['audience'], 'Business owners')

    def test_readiness_returns_actionable_profile_error(self):
        with patch.dict(os.environ, MARKETING_AUTOMATION_ENABLED='true', PUBLISHING_ENABLED='false', DD_LOGS_ENABLED='false'), \
                patch.object(main, 'store', return_value=Mock(queued=Mock(return_value=[]))), \
                patch.object(marketing, 'profile', side_effect=marketing.ProfileError('Missing fields: audience, business_facts')), \
                patch.object(marketing, 'delivery_config'):
            result = main.readiness()
        self.assertEqual(result['missing_configuration'], ['marketing_profile'])
        self.assertIn('audience, business_facts', result['configuration_errors']['marketing_profile'])


class MarketingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Store(Path(self.directory.name) / 'runs.sqlite3')
        self.env = patch.dict(os.environ, {'FACEBOOK_GRAPH_VERSION': 'v99.0', 'FACEBOOK_PAGE_ID': '123',
            'FACEBOOK_PAGE_ACCESS_TOKEN': 'test-page-secret', 'PUBLISHING_ENABLED': 'true',
            'PUBLIC_API_BASE_URL': 'https://crew.example', 'MARKETING_API_KEY': 'test-key',
            'MARKETING_AUTOMATION_ENABLED': 'true', 'AUTO_APPROVAL_ENABLED': 'true', 'LLM_MODEL': 'test-model',
            'ARTICLE_ARTWORK_ENABLED': 'false'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.profile = patch.object(marketing, 'profile', return_value=config())
        self.profile.start(); self.addCleanup(self.profile.stop)
        destination = patch.object(marketing, 'facebook_destination', return_value=('v99.0', '123', 'test-page-secret', 'Bun2too'))
        destination.start(); self.addCleanup(destination.stop)
        data = patch.object(main, 'DATA_DIR', Path(self.directory.name))
        data.start(); self.addCleanup(data.stop)
        self.client = TestClient(main.app)
        self.client.headers['Authorization'] = 'Bearer test-key'

    def prepared(self):
        run = self.db.create({'channels': ['facebook']})
        content = artifact()
        self.db.update(run['id'], artifact=content, status='approved',
            tasks=[{'agent': role, 'structured': {'approved_for_publication': True}} for role in ('tester', 'editor')],
            approval={'sha256': hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()})
        return run['id']

    def test_daily_slot_deduplicates_concurrent_ticks_and_survives_reopen(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.db.schedule('today', {'campaign_key': 'bun2too-daily'}), range(16)))
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len({run['id'] for run, _ in results}), 1)
        reopened = Store(self.db.path)
        self.assertFalse(reopened.schedule('today', {'campaign_key': 'bun2too-daily'})[1])

    def test_random_window_is_stable_bounded_and_handles_dst(self):
        times = set()
        for month in (1, 7, 11):
            instant = datetime(2026, month, 15, 18, tzinfo=timezone.utc)
            after, before = marketing.publication_window(config(), instant)
            self.assertEqual((after, before), marketing.publication_window(config(), instant))
            self.assertGreaterEqual(after.hour, 8)
            self.assertLess(after, before)
            self.assertEqual(before.strftime('%H:%M'), '22:30')
            self.assertEqual(after.utcoffset().total_seconds(), -21600 if month != 7 else -18000)
            times.add(after.strftime('%H:%M'))
        self.assertGreater(len(times), 1)
        self.assertIsNone(marketing.schedule_slot(config(), datetime(2026, 7, 15, 7, tzinfo=ZoneInfo('America/Chicago'))))
        self.assertIsNone(marketing.schedule_slot(config(), datetime(2026, 7, 15, 23, tzinfo=ZoneInfo('America/Chicago'))))

    def test_restart_only_retries_generation_twice(self):
        run, _ = self.db.schedule('today', {'campaign_key': 'bun2too-daily'})
        self.db.update(run['id'], status='running', attempts=1)
        self.db.recover_generation()
        self.assertEqual(self.db.get(run['id'])['status'], 'queued')
        self.db.update(run['id'], status='running', attempts=2)
        self.db.recover_generation()
        self.assertEqual(self.db.get(run['id'])['status'], 'failed')

    def test_timeout_is_unknown_and_cannot_double_post(self):
        run_id = self.prepared()
        with patch.object(marketing.httpx, 'post', side_effect=httpx.ReadTimeout('secret response')) as send:
            result = marketing.publish_one(self.db, run_id)
            self.assertEqual(result['status'], 'unknown')
            with self.assertRaises(ValueError): marketing.publish_one(self.db, run_id)
            send.assert_called_once()
        self.assertNotIn('secret response', json.dumps(self.db.social_recent()))

    def test_parallel_claims_only_one_send(self):
        run_id = self.prepared()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.db.claim_social(run_id, '123', '2026-01-01', 1), range(16)))
        self.assertEqual(sum(p['acquired'] for p in results), 1)

    def test_success_and_daily_cap(self):
        run_id = self.prepared()
        response = httpx.Response(200, json={'id': '123_456'}, request=httpx.Request('POST', 'https://graph.facebook.com'))
        with patch.object(marketing.httpx, 'post', return_value=response) as send:
            result = marketing.publish_one(self.db, run_id)
            self.assertEqual(result['remote_id'], '123_456')
            self.assertEqual(send.call_args.kwargs['data']['link'], 'https://crew.example/articles/' + run_id)
            with self.assertRaisesRegex(ValueError, 'Daily'): marketing.publish_one(self.db, self.prepared())
            send.assert_called_once()

    def test_policy_reviews_hash_and_window_prevent_publication(self):
        run_id = self.prepared()
        with patch.object(marketing.httpx, 'post') as send:
            self.db.update(run_id, tasks=[])
            with self.assertRaisesRegex(ValueError, 'Tester and Editor'): marketing.publish_one(self.db, run_id)
            run_id = self.prepared(); content = artifact(); content['posts'][0]['text'] = 'Altered'
            self.db.update(run_id, artifact=content)
            with self.assertRaisesRegex(ValueError, 'hash'): marketing.publish_one(self.db, run_id)
            run_id = self.prepared(); now = datetime.now(timezone.utc)
            self.db.update(run_id, scheduled=True, publish_after=(now+timedelta(hours=1)).isoformat(), publish_before=(now+timedelta(hours=2)).isoformat())
            with self.assertRaisesRegex(ValueError, 'not due'): marketing.publish_one(self.db, run_id)
            self.db.update(run_id, publish_after=(now-timedelta(hours=2)).isoformat(), publish_before=(now-timedelta(hours=1)).isoformat())
            with self.assertRaisesRegex(ValueError, 'expired'): marketing.publish_one(self.db, run_id)
            self.assertEqual(self.db.get(run_id)['status'], 'expired')
            send.assert_not_called()

    def test_no_scheduled_job_or_model_spend_without_delivery(self):
        for overrides in ({'PUBLISHING_ENABLED':'false'}, {'FACEBOOK_PAGE_ACCESS_TOKEN':''},
                          {'FACEBOOK_PAGE_ID':''}, {'PUBLIC_API_BASE_URL':''}):
            with self.subTest(overrides=list(overrides)), patch.dict(os.environ, overrides), patch.object(main, 'build_crew') as build:
                response = self.client.post('/automation/tick')
                self.assertEqual(response.status_code, 409)
                self.assertEqual(self.db.queued(), [])
                build.assert_not_called()

    def test_queued_job_does_not_spend_after_delivery_disabled(self):
        run, _ = self.db.schedule('disabled-after-queue', {'campaign_key':'bun2too-daily','channels':['facebook']})
        with patch.dict(os.environ, {'PUBLISHING_ENABLED':'false'}), patch.object(main, 'build_crew') as build:
            main.execute_run(run['id'])
            build.assert_not_called()
        self.assertEqual(self.db.get(run['id'])['status'], 'failed')

    def test_source_fetch_rejects_local_network_and_non_https(self):
        with self.assertRaises(ValueError): marketing.source_context({'research_feeds':['http://example.com']})
        with patch.object(marketing.socket, 'getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): marketing.source_context({'research_feeds':['https://example.com']})

    def test_recent_feed_research_is_sorted_diverse_and_bounded(self):
        now = datetime(2026, 10, 2, 18, tzinfo=timezone.utc)
        feeds = {
            'https://one.example/feed': b'''<rss><channel>
              <item><title>Newest one</title><link>https://one.example/new</link><pubDate>Thu, 02 Oct 2026 17:00:00 GMT</pubDate><description>New technical release details.</description></item>
              <item><title>Older one</title><link>https://one.example/old</link><pubDate>Wed, 01 Oct 2026 17:00:00 GMT</pubDate><description>Earlier details.</description></item>
              <item><title>Stale</title><link>https://one.example/stale</link><pubDate>Mon, 01 Sep 2026 17:00:00 GMT</pubDate><description>Too old.</description></item>
            </channel></rss>''',
            'https://two.example/feed': b'''<feed xmlns="http://www.w3.org/2005/Atom">
              <entry><title>Newest two</title><link href="https://two.example/new"/><updated>2026-10-02T16:00:00Z</updated><summary>Another current topic.</summary></entry>
            </feed>''',
        }
        settings = dict(research_feeds=list(feeds), source_urls=[], research_max_age_days=7, research_item_limit=3)
        with patch.object(marketing, '_download', side_effect=lambda url, limit: feeds[url]), \
                patch.object(marketing, '_public_https'):
            sources, failures = marketing.source_context(settings, now)
        self.assertEqual([source['title'] for source in sources], ['Newest one', 'Newest two', 'Older one'])
        self.assertEqual(failures, [])
        self.assertNotIn('Stale', json.dumps(sources))

    def test_research_uses_healthy_feeds_and_reports_failed_ones(self):
        now = datetime(2026, 10, 2, 18, tzinfo=timezone.utc)
        feed = b'''<rss><channel><item><title>Current</title><link>https://good.example/item</link>
          <pubDate>Thu, 02 Oct 2026 17:00:00 GMT</pubDate><description>Current evidence.</description></item></channel></rss>'''
        def download(url, limit):
            if 'bad' in url: raise httpx.ConnectError('unavailable')
            return feed
        settings = dict(research_feeds=['https://bad.example/feed','https://good.example/feed'], source_urls=[],
                        research_max_age_days=7, research_item_limit=3)
        with patch.object(marketing, '_download', side_effect=download), patch.object(marketing, '_public_https'):
            sources, failures = marketing.source_context(settings, now)
        self.assertEqual(len(sources), 1)
        self.assertEqual(failures, [{'feed_url':'https://bad.example/feed','error_type':'ConnectError'}])

    def test_research_check_reports_current_sources_without_article_text(self):
        now = datetime.now(timezone.utc)
        sources = [dict(url='https://news.example/current', feed_url='https://news.example/feed',
                        title='Private response title', published_at=now.isoformat(),
                        retrieved_at=now.isoformat(), text='Private response article text')]
        with patch.object(marketing, 'source_context', return_value=(sources, [])):
            response = self.client.get('/automation/research-check')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['recent_item_count'], 1)
        self.assertEqual(result['source_domains'], ['news.example'])
        self.assertNotIn('Private response', response.text)

    def test_scheduled_cycle_generation_approval_publication_and_metrics(self):
        now = datetime.now(timezone.utc)
        with patch.object(marketing, 'schedule_slot', return_value='today'), patch.object(marketing, 'publication_window', return_value=(now-timedelta(minutes=1), now+timedelta(hours=1))):
            first = self.client.post('/automation/tick').json()
            second = self.client.post('/automation/tick').json()
        self.assertTrue(first['created']); self.assertFalse(second['created'])
        captured = {}
        def build(brief, record, **kwargs):
            captured.update(brief)
            def kickoff():
                for role in ('product_owner','business_analyst','researcher','creative','writer','engineering','tester','editor','delivery'):
                    record(role, 'Evidence', {'approved_for_publication': role in ('tester','editor')})
                return SimpleNamespace(pydantic=MarketingArtifact.model_validate(artifact()))
            return SimpleNamespace(kickoff=kickoff)
        recent = [dict(url='https://news.example/item', feed_url='https://news.example/feed', title='Current topic',
                       published_at=now.isoformat(), retrieved_at=now.isoformat(), text='Current verified evidence')]
        with patch.object(marketing, 'source_context', return_value=(recent, [])), \
                patch.object(main, 'build_crew', side_effect=build): main.execute_run(first['run_id'])
        self.assertEqual(self.db.get(first['run_id'])['status'], 'approved')
        self.assertIn('observed_results', captured)
        self.assertIn('recent_research', captured['source_material'])
        self.assertTrue(captured['publishing_context']['page_identity_verified'])
        self.assertTrue(captured['publishing_context']['automatic_approval_enabled'])
        self.assertEqual(captured['publishing_context']['article_url'], 'https://crew.example/articles/' + first['run_id'])
        response = httpx.Response(200, json={'id':'123_456'}, request=httpx.Request('POST','https://graph.facebook.com'))
        with patch.object(marketing.httpx, 'post', return_value=response):
            published = self.client.post('/automation/publish').json()['publications'][0]
        self.assertEqual(published['status'], 'published')
        self.assertEqual(self.client.get('/articles/'+first['run_id']).status_code, 200)
        self.assertEqual(self.client.post('/automation/publish').json()['publications'], [])
        metrics = httpx.Response(200,json={'reactions':{'summary':{'total_count':3}}},request=httpx.Request('GET','https://graph.facebook.com'))
        with patch.object(marketing.httpx, 'get', return_value=metrics): self.client.post('/automation/metrics')
        self.assertEqual(self.db.social_recent()[0]['metrics'], {'reactions':3})

    def test_article_is_private_until_dispatch_and_escaped(self):
        run_id = self.prepared()
        self.assertEqual(self.client.get('/articles/'+run_id).status_code, 404)
        content = artifact(); content['articles'][0]['title'] = '<script>alert(1)</script>'
        self.db.update(run_id, artifact=content, status='publishing')
        response = self.client.get('/articles/'+run_id)
        self.assertNotIn('<script>', response.text)
        self.assertIn('&lt;script&gt;', response.text)
        self.assertIn('BUN2TOO', response.text)
        self.assertIn('class="hero fallback"', response.text)
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])

    def test_generated_artwork_is_bounded_persisted_and_served(self):
        webp = b'RIFF' + (120).to_bytes(4, 'little') + b'WEBP' + b'x' * 120
        image = SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(webp).decode())])
        client = Mock(images=Mock(generate=Mock(return_value=image)))
        content = artifact()
        with patch.dict(os.environ, ARTICLE_ARTWORK_ENABLED='true', OPENAI_API_KEY='test-image-key'), \
                patch('openai.OpenAI', return_value=client):
            result = marketing.generate_article_artwork(main.DATA_DIR, 'article-1', content)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['model'], 'gpt-image-2.5-flare')
        self.assertNotIn('prompt', result)
        request = client.images.generate.call_args.kwargs
        self.assertEqual(request['size'], '1536x1024')
        self.assertEqual(request['output_format'], 'webp')
        self.assertIn('No words', request['prompt'])
        run_id = self.prepared()
        target = main.DATA_DIR / 'article-assets' / (run_id + '.webp')
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(webp)
        self.db.update(run_id, status='published', article_artwork=dict(result, filename=run_id + '.webp'))
        page = self.client.get('/articles/' + run_id)
        self.assertIn('/artwork.webp', page.text)
        self.assertIn('property="og:image"', page.text)
        asset = self.client.get('/articles/' + run_id + '/artwork.webp')
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.headers['content-type'], 'image/webp')
        self.assertEqual(asset.content, webp)
        index = self.client.get('/insights')
        self.assertIn('Useful article', index.text)
        self.assertIn('/articles/' + run_id + '/artwork.webp', index.text)
        self.assertEqual(self.client.get('/', follow_redirects=False).headers['location'], '/insights')

    def test_artwork_failure_uses_fallback_without_blocking_content(self):
        run = self.db.create({'channels': ['facebook']})
        with patch.object(marketing, 'generate_article_artwork', side_effect=httpx.ReadTimeout('private')):
            result = main.create_article_artwork(self.db, run['id'], artifact())
        self.assertEqual(result, {'status': 'failed', 'error_type': 'ReadTimeout'})
        event = self.db.events(run['id'])[-1]
        self.assertEqual(event['kind'], 'article_artwork_failed')
        self.assertEqual(event['status'], 'partial')
        self.assertNotIn('private', json.dumps(event))

    def test_lifespan_worker_consumes_durable_job(self):
        import time
        run, _ = self.db.schedule('worker-test', {'campaign_key': 'bun2too-daily', 'channels': ['facebook']})
        crew = SimpleNamespace(kickoff=lambda: SimpleNamespace(pydantic=MarketingArtifact.model_validate(artifact())))
        recent = [dict(url='https://news.example/item', feed_url='https://news.example/feed', title='Current topic',
                       published_at=datetime.now(timezone.utc).isoformat(),
                       retrieved_at=datetime.now(timezone.utc).isoformat(), text='Current evidence')]
        with patch.dict(os.environ, {'WORKER_ENABLED': 'true', 'DD_LOGS_ENABLED': 'false'}), \
                patch.object(marketing, 'source_context', return_value=(recent, [])), \
                patch.object(main, 'build_crew', return_value=crew):
            with TestClient(main.app) as client:
                for _ in range(100):
                    if self.db.get(run['id'])['status'] == 'awaiting_review': break
                    time.sleep(0.02)
                self.assertEqual(self.db.get(run['id'])['status'], 'awaiting_review')
                # Missing independent reviews hold the draft even with automatic policy enabled.
                self.assertTrue(main.worker_ready.is_set())
        self.assertFalse(main.worker_ready.is_set())

    def test_reconcile_verifies_existing_post_without_resending(self):
        run_id = self.prepared()
        claim = self.db.claim_social(run_id, '123', '2026-01-01', 1)
        self.db.finish_social(claim['id'], 'unknown')
        response = httpx.Response(200, json={'id':'123_456','message':artifact()['posts'][0]['text']},request=httpx.Request('GET','https://graph.facebook.com'))
        with patch.object(main.httpx, 'get', return_value=response), patch.object(main.httpx, 'post') as send:
            result = self.client.post('/social-publications/'+claim['id']+'/reconcile', json={'remote_id':'123_456','reviewer':'owner'})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['status'], 'published')
            send.assert_not_called()

    def test_log_export_is_retryable_and_excludes_prompt_and_secrets(self):
        self.db.event('run-1','task_completed',agent='writer',prompt='Private source text',token='sensitive')
        with patch.dict(os.environ, {'DD_LOGS_ENABLED':'true','DD_API_KEY':'test-dd-key','DD_SITE':'us5.datadoghq.com'}):
            with patch.object(telemetry.httpx, 'post', side_effect=httpx.ReadTimeout('failure')):
                telemetry.flush(self.db)
            self.assertEqual(len(self.db.log_batch()),1)
            with patch.object(telemetry.httpx, 'post', return_value=httpx.Response(202,request=httpx.Request('POST','https://example.com'))) as send:
                telemetry.flush(self.db)
                payload=json.dumps(send.call_args.kwargs['json'])
                self.assertNotIn('Private source text',payload); self.assertNotIn('sensitive',payload)
            self.assertEqual(self.db.log_batch(),[])

    def test_datadog_status_reports_rejection_and_recovery_without_secrets(self):
        self.db.event('runtime', 'runtime_started', status='ready')
        with patch.dict(os.environ, DD_LOGS_ENABLED='true', DD_API_KEY='private-dd-key', DD_SITE='us5.datadoghq.com'):
            response = httpx.Response(403, request=httpx.Request('POST', 'https://example.com'))
            with patch.object(telemetry.httpx, 'post', return_value=response):
                telemetry.flush(self.db)
            state = telemetry.status(self.db)
            self.assertEqual(state['last_export']['http_status'], 403)
            self.assertEqual(state['pending_batch_count'], 1)
            self.assertNotIn('private-dd-key', json.dumps(state))
            with patch.object(telemetry.httpx, 'post', return_value=httpx.Response(202, request=httpx.Request('POST', 'https://example.com'))):
                telemetry.flush(self.db)
            self.assertEqual(telemetry.status(self.db)['last_export']['status'], 'accepted')
            self.assertEqual(telemetry.status(self.db)['pending_batch_count'], 0)


if __name__ == '__main__': unittest.main()


class EditorialDiversityTests(unittest.TestCase):
    def test_busy_feed_cannot_fill_all_remaining_slots(self):
        instant = datetime(2026, 10, 13, tzinfo=timezone.utc)
        def items(feed, at):
            return [dict(url=feed + '/' + str(i), feed_url=feed, title=str(i), text='Evidence',
                         published_at=(instant - timedelta(hours=i + (10 if feed == 'slow' else 0))).isoformat())
                    for i in range(8)]
        with patch.object(marketing, '_feed_items', side_effect=items):
            sources, _ = marketing.source_context({'research_feeds': ['busy', 'slow'], 'research_item_limit': 6}, instant)
        self.assertEqual([s['feed_url'] for s in sources], ['busy', 'slow'] * 3)

    def test_rotation_covers_seven_themes_and_rejects_repeat_headline_provider(self):
        db = Mock(published_between=Mock(return_value=[]))
        themes = set()
        for day in range(1, 8):
            context = marketing.editorial_context(db, {'id': 'new', 'created_at': f'2026-10-{day:02}T12:00:00+00:00'}, config())
            themes.add(context['theme'])
        self.assertEqual(len(themes), 7)
        content = artifact()
        content['articles'][0]['title'] = 'Copilot for enterprise engineering'
        run = dict(artifact=content, editorial_context={'recent_publications': [{'title': 'Microsoft AI updates'}]})
        with self.assertRaisesRegex(ValueError, 'repeats a provider'):
            marketing.check_artifact(run)
        content['articles'][0]['title'] = 'Evaluating enterprise AI safely'
        marketing.check_artifact(run)

    def test_history_includes_more_than_twenty_posts_and_ignores_metric_refresh_age(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Store(Path(directory) / 'runs.db')
            instant = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
            for i in range(22):
                run = db.create({'brief': 'AI'})
                content = artifact()
                content['articles'][0]['title'] = 'Copilot baseline' if i == 0 else f'Article {i}'
                db.update(run['id'], status='published', artifact=content)
                record = {'id': f'post-{i}', 'run_id': run['id'], 'status': 'published',
                          'created_at': (instant - timedelta(days=2)).isoformat(),
                          'updated_at': instant.isoformat()}
                with db.connect() as connection:
                    connection.execute('INSERT INTO social_posts VALUES (?, ?, ?)',
                                       (record['id'], run['id'], json.dumps(record)))
            run = {'id': 'new', 'created_at': instant.isoformat()}
            history = marketing.editorial_context(db, run, config())['recent_publications']
            self.assertEqual(len(history), 22)
            self.assertIn('Copilot baseline', [item['title'] for item in history])
            with db.connect() as connection:
                record['created_at'] = (instant - timedelta(days=9)).isoformat()
                connection.execute('UPDATE social_posts SET data = ? WHERE id = ?',
                                   (json.dumps(record), record['id']))
            self.assertEqual(len(marketing.editorial_context(db, run, config())['recent_publications']), 21)
