import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from openai import RateLimitError

from crewai_agents.app import main, notifications, operations, recovery, marketing
from crewai_agents.app.observability import error_details
from crewai_agents.app.store import Store, now


def billing_diagnostic():
    request = httpx.Request('POST', 'https://api.openai.com/v1/chat/completions')
    try:
        try:
            raise RateLimitError('No credits remaining', response=httpx.Response(429, request=request),
                                 body={'type': 'insufficient_quota', 'code': 'credit_balance_exhausted'})
        except RateLimitError as exc:
            raise RuntimeError('Framework wrapper') from exc
    except RuntimeError as exc:
        return error_details(exc)


class OperationsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Store(Path(directory.name) / 'runs.db')
        env = patch.dict(os.environ, ALERTS_ENABLED='true', ALERT_SLACK_BOT_TOKEN='test-slack-secret',
            ALERT_SLACK_CHANNEL='C123', SMTP_HOST='', ALERT_EMAIL_FROM='', ALERT_EMAIL_TO='bun2too@gmail.com',
            WORKFLOW_HEARTBEAT_ENABLED='false', MARKETING_API_KEY='test-key', LANGSMITH_TRACING='false',
            DD_LLMOBS_ENABLED='0', ALERT_REMINDER_SECONDS='21600')
        env.start(); self.addCleanup(env.stop)

    def scheduled(self, **changes):
        run, _ = self.db.schedule(now(), {'campaign_key': 'daily', 'brief': 'AI', 'channels': ['facebook']},
            publish_before=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat())
        return self.db.update(run['id'], **changes)

    def test_billing_429_is_permanent_but_rate_limit_and_server_errors_retry(self):
        policy = recovery.classify(billing_diagnostic())
        self.assertFalse(policy['retryable']); self.assertTrue(policy['pause_generation'])
        for cause in ({'status_code': '429', 'provider_code': 'rate_limit_exceeded'}, {'status_code': '503'}, {'type': 'TimeoutError'}):
            policy = recovery.classify({'causes': [cause]}, 2)
            self.assertTrue(policy['retryable']); self.assertFalse(policy['pause_generation'])
            self.assertGreaterEqual(policy['delay_seconds'], 120)
        policy = recovery.classify({'causes': [{'status_code': '429', 'retry_after_seconds': 900}]})
        self.assertEqual(policy['delay_seconds'], 900)
        self.assertFalse(recovery.classify({'causes': [{'status_code': '400'}]})['retryable'])
        self.assertTrue(recovery.classify({'causes': [{'status_code': '401'}]})['pause_generation'])

    def test_bootstrap_pauses_old_billing_failure_even_if_legacy_retryable_true(self):
        run = self.scheduled(status='failed', attempts=3, retryable=True, error_details=billing_diagnostic())
        operations.bootstrap(self.db)
        self.assertEqual(operations.circuit(self.db)['run_id'], run['id'])
        with self.assertRaises(ValueError):
            self.db.retry_generation(run['id'], 'automatic', automatic=True)
        with patch.object(main, 'store', return_value=self.db), patch.object(main, 'build_crew') as build:
            main.execute_run(run['id'])
            build.assert_not_called()
        self.assertEqual(operations.inspect_runs(self.db), [])
        self.assertEqual(self.db.get(run['id'])['attempts'], 3)
        operations.resume(self.db, 'operator after billing restored', run['id'])
        self.assertIsNone(operations.circuit(self.db))
        self.assertEqual(self.db.get(run['id'])['status'], 'queued')
        operations.bootstrap(self.db)
        self.assertIsNone(operations.circuit(self.db))

    def test_transient_retry_backoff_limit_window_and_no_social_replay(self):
        diagnostic = {'causes': [{'type': 'TimeoutError'}]}
        run = self.scheduled(status='failed', retryable=True, attempts=1, error_details=diagnostic,
                             retry_after=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
        self.assertEqual(operations.inspect_runs(self.db), [])
        self.db.update(run['id'], retry_after=now())
        self.assertEqual(operations.inspect_runs(self.db)[0]['action'], 'generation_retry_queued')
        self.assertEqual(operations.inspect_runs(self.db), [])
        self.db.update(run['id'], status='failed', attempts=3)
        self.assertEqual(operations.inspect_runs(self.db), [])
        self.db.update(run['id'], status='approved', attempts=1)
        post = self.db.claim_social(run['id'], '123', '2026-10-16', 1)
        self.db.finish_social(post['id'], 'unknown')
        with patch.object(marketing, 'publish_one') as send:
            operations.inspect_runs(self.db)
            send.assert_not_called()
        self.assertEqual(self.db.social(post['id'])['status'], 'unknown')

    def test_alert_dedupe_concurrency_restart_missing_email_and_recovery(self):
        def open_incident(_):
            notifications.incident(self.db, 'campaign:one', 'Failure', 'Provider billing is exhausted', 'one')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(open_incident, range(10)))
        self.assertEqual(notifications.status(self.db)['deliveries'], {'slack:pending': 1, 'email:pending': 1})
        with patch.object(notifications, 'send', return_value={'remote_id': 'message-1'}) as send:
            notifications.deliver(Store(self.db.path))
            notifications.deliver(self.db)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(notifications.status(self.db)['deliveries'], {'slack:sent': 1, 'email:blocked': 1})
        with patch.dict(os.environ, SMTP_HOST='smtp.example', ALERT_EMAIL_FROM='alerts@example.com'), \
                patch.object(notifications, 'send', return_value={'remote_id': 'email-1'}) as send:
            notifications.deliver(self.db)
            self.assertEqual(send.call_count, 1)
        notifications.resolve(self.db, 'campaign:one', 'Published')
        notifications.resolve(self.db, 'campaign:one', 'Published')
        self.assertEqual(sum(notifications.status(self.db)['deliveries'].values()), 4)

    def test_failed_channel_does_not_block_other_channel_and_retry_is_bounded(self):
        notifications.incident(self.db, 'test', 'Test', 'test')
        def send(item):
            if item['channel'] == 'slack': raise httpx.ConnectError('unreachable secret')
            return {'remote_id': 'email-1'}
        with patch.dict(os.environ, SMTP_HOST='smtp.example', ALERT_EMAIL_FROM='alerts@example.com'), patch.object(notifications, 'send', side_effect=send):
            notifications.deliver(self.db)
        state = notifications.status(self.db)
        self.assertEqual(state['deliveries']['email:sent'], 1)
        pending = next(item for item in state['recent_deliveries'] if item['channel'] == 'slack')
        self.assertEqual(pending['attempts'], 1)
        self.assertNotIn('unreachable secret', json.dumps(state))
        with self.db.connect() as connection:
            record = json.loads(connection.execute('SELECT data FROM alert_deliveries WHERE id=?', (pending['id'],)).fetchone()[0])
            record.update(status='exhausted', attempts=5)
            connection.execute('UPDATE alert_deliveries SET data=? WHERE id=?', (json.dumps(record), record['id']))
        with patch.object(notifications, 'send') as send:
            notifications.deliver(self.db); send.assert_not_called()
        notifications.retry(self.db, record['id'], 'operator')
        self.assertEqual(next(x for x in notifications.status(self.db)['recent_deliveries'] if x['id'] == record['id'])['attempts'], 0)

    def test_failure_reason_propagates_from_nested_campaign_and_notifications_dedupe(self):
        run = self.scheduled(status='failed', error='AI provider credits exhausted')
        client = TestClient(main.app); client.headers['Authorization'] = 'Bearer test-key'
        with patch.object(main, 'store', return_value=self.db):
            response = client.post('/automation/events', json={'execution_id':'one','workflow_name':'marketing',
                'status':'completed','result':{'status':'blocked','campaigns':[{'run_id':run['id'],'status':'failed','reason':'AI provider credits exhausted'}]}})
            self.assertEqual(response.json()['reason'], 'AI provider credits exhausted')
            client.post('/automation/events', json={'execution_id':'one','workflow_name':'marketing','status':'failed',
                'error_message':'AI provider credits exhausted; runs=' + run['id']})
        self.assertEqual(notifications.status(self.db)['deliveries'], {'slack:pending':1,'email:pending':1})

    def test_heartbeat_and_recovery_with_no_auto_restart(self):
        with patch.dict(os.environ, WORKFLOW_HEARTBEAT_ENABLED='true'):
            operations.save(self.db, 'watchdog_started', {'at': (datetime.now(timezone.utc)-timedelta(hours=27)).isoformat()})
            operations.heartbeat_check(self.db)
            self.assertEqual(len(notifications.status(self.db)['incidents']), 1)
            for operation in ('Generate daily campaign', 'Publish approved content'):
                self.db.event('n8n:1','n8n_execution_failed', operation=operation)
            operations.heartbeat_check(self.db)
            self.assertTrue(all(x['status']=='resolved' for x in notifications.status(self.db)['incidents']))

    def test_daily_heartbeat_does_not_alert_between_daily_runs(self):
        with patch.dict(os.environ, WORKFLOW_HEARTBEAT_ENABLED='true', WORKFLOW_HEARTBEAT_SECONDS='1200'):
            operations.save(self.db, 'watchdog_started', {'at': (datetime.now(timezone.utc)-timedelta(hours=27)).isoformat()})
            self.db.event('n8n:daily', 'n8n_execution_completed', operation='Generate daily campaign')
            operations.heartbeat_check(self.db)
            self.assertEqual(notifications.status(self.db)['incidents'], [])

    def test_real_channel_adapters_use_secure_smtp_and_check_slack_business_error(self):
        item = {'id':'test-id','channel':'email','incident':{'status':'open','title':'Failure','reason':'No credits',
                'key':'campaign:test','episode':1,'run_id':'test'}}
        smtp = Mock(); smtp.__enter__ = Mock(return_value=smtp); smtp.__exit__ = Mock(return_value=False)
        smtp.send_message.return_value = {}
        with patch.dict(os.environ, SMTP_HOST='smtp.example', SMTP_USER='alerts', SMTP_PASSWORD='test-smtp-secret',
                        ALERT_EMAIL_FROM='alerts@example.com', SMTP_PORT='587'), patch.object(notifications.smtplib,'SMTP',return_value=smtp):
            notifications.send(item)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with('alerts','test-smtp-secret')
        self.assertEqual(smtp.send_message.call_args.args[0]['To'],'bun2too@gmail.com')
        item['channel']='slack'
        response = httpx.Response(200,json={'ok':False,'error':'not_in_channel'},request=httpx.Request('POST','https://slack.com/api/chat.postMessage'))
        with patch.object(notifications.httpx,'post',return_value=response), self.assertRaises(ValueError):
            notifications.send(item)

    def test_expired_queued_campaign_is_not_regenerated(self):
        run = self.scheduled(status='queued', publish_before=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat())
        with patch.object(main,'store',return_value=self.db), patch.object(main,'build_crew') as build:
            main.execute_run(run['id'])
        self.assertEqual(self.db.get(run['id'])['status'],'expired')
        build.assert_not_called()

    def test_simultaneous_delivery_workers_claim_once(self):
        notifications.incident(self.db,'campaign:test','Test','Test')
        with patch.object(notifications,'send',return_value={'remote_id':'one'}) as send:
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(lambda _: notifications.deliver(self.db),range(3)))
            self.assertEqual(send.call_count,1)

    def test_recovery_endpoints_require_auth_and_resume_without_sending(self):
        run = self.scheduled(status='failed', error_details=billing_diagnostic(), attempts=3)
        operations.bootstrap(self.db)
        client = TestClient(main.app)
        with patch.object(main,'store',return_value=self.db), patch.object(marketing,'publish_one') as send:
            self.assertEqual(client.post('/automation/recovery/resume',json={'reviewer':'operator'}).status_code,401)
            client.headers['Authorization']='Bearer test-key'
            response=client.post('/automation/recovery/resume',json={'reviewer':'operator','run_id':run['id']})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['status'],'queued')
            send.assert_not_called()

    def test_legacy_failure_summary_and_workflow_resolution(self):
        run=self.scheduled(status='failed',error='Generation failed (RuntimeError)',error_details=billing_diagnostic())
        self.assertIn('credits',main.campaign_state(run)['reason'])
        notifications.incident(self.db,'workflow:marketing:Generate daily campaign','Workflow failure','Connection failed')
        with patch.object(main,'store',return_value=self.db):
            main.workflow_event(main.WorkflowEvent(execution_id='recovery',workflow_name='marketing',
                node='Generate daily campaign',status='completed'))
        self.assertEqual(notifications.status(self.db)['incidents'][0]['status'],'resolved')

    def test_retry_exhaustion_escalation_is_not_downgraded_by_workflow_checks(self):
        notifications.incident(self.db,'test','Test','Transient failure')
        notifications.incident(self.db,'test','Test','Retries exhausted',severity='critical')
        notifications.incident(self.db,'test','Test','Still failed',severity='error')
        notifications.incident(self.db,'test','Test','Retries exhausted',severity='critical')
        status=notifications.status(self.db)
        self.assertEqual(sum(status['deliveries'].values()),4)
        self.assertEqual(status['incidents'][0]['severity'],'critical')
