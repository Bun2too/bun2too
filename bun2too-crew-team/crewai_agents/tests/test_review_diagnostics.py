import copy
import unittest
from crewai_agents.app import main, marketing


class ReviewDiagnosticsTests(unittest.TestCase):
    def run_record(self):
        return dict(id='run', status='awaiting_review', created_at='2026-10-21T13:00:00+00:00',
                    publication_blocker='Artifact has unresolved blockers',
                    artifact={'blockers': ['Unsupported performance claim', 'Editor requested a source']},
                    tasks=[{'agent':'tester', 'structured': {'approved_for_publication':False,
                        'summary':'Performance claim lacks evidence', 'decisions':['Remove the number'], 'risks':[]}},
                           {'agent':'editor', 'structured': {'approved_for_publication':True, 'summary':'Edited copy approved'}}])

    def test_legacy_state_exposes_evidence_without_approving_or_mutating(self):
        run = self.run_record(); before = copy.deepcopy(run)
        result = main.campaign_state(run)
        self.assertIn('Unsupported performance claim', result['reason'])
        self.assertEqual(result['review_details']['blocker_count'], 2)
        self.assertFalse(result['review_details']['reviews']['tester']['approved_for_publication'])
        self.assertTrue(result['review_details']['reviews']['editor']['approved_for_publication'])
        self.assertEqual(run, before)
        self.assertEqual(result['status'], 'awaiting_review')
        self.assertFalse(result['retryable'])

    def test_gate_still_rejects_blockers_with_actionable_message(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported performance claim'):
            marketing.check_artifact(self.run_record())

    def test_missing_reviews_are_not_approval_and_messages_are_bounded(self):
        run = self.run_record(); run['tasks'] = []; run['artifact']['blockers'] = ['x'*5000]*25
        details = marketing.review_diagnostics(run)
        self.assertEqual(details['blocker_count'], 25)
        self.assertEqual(len(details['blockers']), 10)
        self.assertLessEqual(len(marketing.publication_blocker_reason(run)), 1300)
        self.assertFalse(details['reviews']['editor']['recorded'])
        self.assertFalse(details['reviews']['editor']['approved_for_publication'])

    def test_secret_redaction_and_specific_failure_preserved(self):
        run = self.run_record(); secret = 'xoxb-' + '1234567890-'*4
        run['artifact']['blockers'] = [secret]
        self.assertNotIn(secret, str(marketing.review_diagnostics(run)))
        self.assertNotIn(secret, marketing.publication_blocker_reason(run))
        run['publication_blocker'] = 'Article cites a source that was not retrieved'
        self.assertEqual(marketing.publication_blocker_reason(run), run['publication_blocker'])


    def test_historical_citation_cannot_be_promoted_to_current_evidence(self):
        run = self.run_record()
        run['artifact'] = {'blockers': [], 'posts': [{'channel': 'facebook', 'text': 'copy'}],
            'articles': [{'title': 'Old topic', 'body': 'body', 'source_urls': ['https://example.com/old']}]}
        run['source_snapshots'] = [{'url': 'https://example.com/current'}]
        run['editorial_context'] = {'recent_publications': [
            {'title': 'Old topic', 'source_urls': ['https://example.com/old']}]}
        with self.assertRaisesRegex(ValueError, 'not retrieved'):
            marketing.check_artifact(run)
        run['publication_blocker'] = 'Article cites a source that was not retrieved'
        result = main.campaign_state(run)
        self.assertIn('https://example.com/old', result['reason'])
        self.assertFalse(result['review_details']['reviews']['tester']['approved_for_publication'])

    def test_feedback_excludes_prior_drafts_and_artwork_but_preserves_metrics(self):
        record = {'run_id': 'old', 'status': 'published', 'metrics': {'likes': 2},
                  'missing_metrics': ['shares'], 'previous_posts': [{'text': 'Copy me', 'asset_brief':'art'}],
                  'previous_hypothesis': 'Preserve old text', 'remote': {'message': 'Copy me'}}
        result = marketing.performance_context([record])
        self.assertEqual(result[0]['metrics'], {'likes': 2})
        self.assertEqual(result[0]['missing_metrics'], ['shares'])
        self.assertNotIn('Copy me', str(result))
        self.assertNotIn('Preserve old text', str(result))

    def test_scheduled_final_review_depends_on_editor_not_original_writer(self):
        import os, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from crewai_agents.app.crews import build_crew
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,
                LLM_MODEL='gpt-4.1', OPENAI_API_KEY='test', MODEL_ROUTING_ENABLED='false', CREWAI_STORAGE_DIR=tmp), \
                patch('crewai_core.token_manager.TokenManager._get_secure_storage_path', return_value=Path(tmp)):
            crew = build_crew({'publishing_context': {'scheduled': True}}, lambda *args: None)
        tasks = {t.name: t for t in crew.tasks}
        order = [t.name for t in crew.tasks]
        self.assertLess(order.index('editor'), order.index('tester'))
        self.assertEqual([t.name for t in tasks['tester'].context], ['researcher', 'editor'])
        self.assertEqual([t.name for t in tasks['delivery'].context], ['creative', 'editor', 'tester'])
        self.assertNotIn('product_owner', [t.name for t in tasks['writer'].context])
        self.assertIn('required to revise', tasks['editor'].description)


class ContentRevisionTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from datetime import datetime, timedelta, timezone
        from crewai_agents.app.store import Store
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.db = Store(self.directory.name + '/db.sqlite')
        run, _ = self.db.schedule('daily-slot', {'campaign_key': 'daily', 'channels': ['facebook']},
            publish_before=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        self.run = self.db.update(run['id'], status='awaiting_review', attempts=1,
            artifact={'blockers':['unsupported citation']}, tasks=[{'agent':'tester', 'structured': {'approved_for_publication':False}}])

    def test_revision_is_atomic_preserves_rejection_and_requires_new_reviews(self):
        from concurrent.futures import ThreadPoolExecutor
        def revise(_):
            try: return self.db.retry_generation(self.run['id'], 'operator', content_revision=True)['status']
            except ValueError: return 'rejected'
        with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(revise,range(4)))
        self.assertEqual(results.count('queued'), 1)
        run = self.db.get(self.run['id'])
        self.assertIsNone(run['approval']); self.assertIsNone(run['artifact']); self.assertEqual(run['tasks'], [])
        self.assertEqual(run['publish_before'], self.run['publish_before'])
        self.assertEqual(run['content_revision_history'][0]['artifact'], self.run['artifact'])
        self.assertEqual(self.db.events(run['id'])[0]['kind'], 'content_revision_requested')

    def test_no_automatic_revision_or_replay_or_expired_revision(self):
        from datetime import datetime, timedelta, timezone
        with self.assertRaises(ValueError):
            self.db.retry_generation(self.run['id'], 'watchdog', automatic=True, content_revision=True)
        self.db.update(self.run['id'], attempts=3)
        with self.assertRaises(ValueError): self.db.retry_generation(self.run['id'], 'operator', content_revision=True)
        self.db.update(self.run['id'], attempts=1, publish_before=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        with self.assertRaisesRegex(ValueError, 'expired'): self.db.retry_generation(self.run['id'], 'operator', content_revision=True)
        self.db.update(self.run['id'], publish_before=self.run['publish_before'])
        self.db.update(self.run['id'], status='approved')
        self.db.claim_social(self.run['id'], 'page', 'today', 1)
        self.db.update(self.run['id'], status='awaiting_review')
        with self.assertRaisesRegex(ValueError, 'publication attempt'): self.db.retry_generation(self.run['id'], 'operator', content_revision=True)

    def test_revision_endpoint_requires_auth_and_does_not_approve(self):
        import os
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        with patch.dict(os.environ, MARKETING_API_KEY='revision-test', MARKETING_AUTOMATION_ENABLED='true'), \
                patch.object(main, 'store', return_value=self.db), \
                patch.object(main.operations, 'circuit', return_value=None), \
                patch.object(marketing, 'delivery_config'), patch.object(main, 'generation_settings'):
            client = TestClient(main.app)
            url = '/runs/' + self.run['id'] + '/revise-content'
            self.assertEqual(client.post(url, json={'reviewer':'operator'}).status_code, 401)
            result = client.post(url, json={'reviewer':'operator'}, headers={'Authorization':'Bearer revision-test'})
            self.assertEqual(result.status_code, 202)
            self.assertEqual(result.json()['status'], 'queued')
            self.assertIsNone(self.db.get(self.run['id'])['approval'])
