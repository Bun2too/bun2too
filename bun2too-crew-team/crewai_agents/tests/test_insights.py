import base64
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET
from fastapi.testclient import TestClient
from crewai_agents.app import main, insights, insights_delivery as delivery
from crewai_agents.app.store import Store


class InsightsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        self.db=Store(self.path/'runs.db');delivery.initialize(self.db)
        self.client=TestClient(main.app)
        self.patch=patch.object(main,'store',return_value=self.db);self.patch.start()
        self.env=patch.dict(os.environ,{'INSIGHTS_UNSUBSCRIBE_SECRET':'test-signing-key-'*4,'INSIGHTS_EMAIL_FROM':'insights@example.com'});self.env.start()
    def tearDown(self): self.patch.stop();self.env.stop();self.temp.cleanup()
    def article(self,status='published'):
        run=self.db.create({'campaign_key':str(self.db.recent()),'channels':['facebook']})
        return self.db.update(run['id'],status=status,approval={'approved_at':datetime.now(timezone.utc).isoformat()},
            artifact={'articles':[{'title':'AI & <systems>','body':'Useful <script>alert(1)</script> ideas.','source_urls':['https://example.com/a?x=1&y=2']}]})
    def user(self):
        return {'user_id':'email|one','email':'reader@example.com','email_verified':True,
            'app_metadata':{'bun2too':{'newsletter':{'status':'subscribed','topics':['ai-automation']}}}}
    def test_public_api_excludes_drafts_failed_publications_and_private_fields(self):
        published=self.article();self.article('approved');self.article('publication_unknown')
        data=self.client.get('/insights/api/articles').json()['articles']
        self.assertEqual(len(data),1);self.assertEqual(data[0]['id'],published['id'])
        self.assertNotIn('approval',data[0]);self.assertNotIn('brief',data[0])
        self.assertEqual(self.client.get('/insights/api/articles/missing').status_code,404)
        self.assertEqual(self.client.get('/insights/api/articles/'+published['id']).status_code,200)
    def test_feeds_escape_content_and_use_stable_ids(self):
        self.article()
        for path in ['/insights/feed.xml','/insights/feed.atom']:
            response=self.client.get(path);self.assertEqual(response.status_code,200)
            root=ET.fromstring(response.content)
            self.assertIn('AI & <systems>',list(root.itertext()))
            self.assertNotIn('<script>',response.text)
    def test_brand_assets_and_subscription_frame(self):
        response=self.client.get('/insights')
        self.assertIn('/insights/signup',response.text);self.assertIn('Services',response.text)
        self.assertIn('frame-src',response.headers['content-security-policy'])
        self.assertEqual(self.client.get('/insights-assets/logoHighRes.png').status_code,200)
        self.assertEqual(self.client.get('/insights-assets/secret.env').status_code,404)
    def subscription(self,endpoint='https://fcm.googleapis.com/fcm/send/test'):
        return {'endpoint':endpoint,'keys':{'p256dh':base64.urlsafe_b64encode(b'\x04'+b'x'*64).decode().rstrip('='),'auth':base64.urlsafe_b64encode(b'x'*16).decode().rstrip('=')}}
    def test_push_validation_blocks_ssrf_and_invalid_crypto_keys(self):
        for url in ['http://fcm.googleapis.com/x','https://127.0.0.1/x','https://fcm.googleapis.com.evil.test/x','https://user:pass@fcm.googleapis.com/x','https://fcm.googleapis.com:8080/x']:
            with self.assertRaises(ValueError):delivery.validate_subscription(self.subscription(url))
        bad=self.subscription();bad['keys']['auth']='x'
        with self.assertRaises(ValueError):delivery.validate_subscription(bad)
    def test_push_requires_consent_origin_and_bounded_body(self):
        with patch.dict(os.environ,INSIGHTS_PUSH_ENABLED='true',INSIGHTS_SITE_URL='https://bun2too.com'):
            payload={'consent':True,'subscription':self.subscription()}
            self.assertEqual(self.client.post('/insights/push-subscriptions',json=payload).status_code,403)
            headers={'Origin':'https://bun2too.com'}
            self.assertEqual(self.client.post('/insights/push-subscriptions',json=payload,headers=headers).status_code,201)
            self.assertEqual(self.client.post('/insights/push-subscriptions',json={**payload,'consent':False},headers=headers).status_code,400)
            self.assertEqual(self.client.post('/insights/push-subscriptions',json={'x':'x'*5000},headers=headers).status_code,413)
    def test_digest_rechecks_consent_and_is_idempotent(self):
        sunday=datetime(2026,11,8,16,tzinfo=timezone.utc)
        article={'id':'a','title':'Useful insight','summary':'Summary','url':'https://bun2too.com/insights/a','published_at':(sunday-timedelta(days=1)).isoformat()}
        directory=Mock();directory.subscribers.return_value=[{'user_id':'email|one'},{'user_id':'email|two'}]
        withdrawn={**self.user(),'email_verified':False}
        directory.user.side_effect=lambda sub:self.user() if sub=='email|one' else withdrawn
        send=Mock()
        delivery.digest(self.db,[article],Mock(return_value=directory),send,sunday)
        delivery.digest(self.db,[article],Mock(return_value=directory),send,sunday)
        send.assert_called_once();directory.close.assert_called()
    def test_ambiguous_digest_is_not_replayed(self):
        sunday=datetime(2026,11,8,16,tzinfo=timezone.utc)
        directory=Mock();directory.subscribers.return_value=[self.user()];directory.user.return_value=self.user()
        send=Mock(side_effect=TimeoutError())
        article={'published_at':sunday.isoformat()}
        with patch.object(delivery.notifications,'incident') as alert:
            for _ in range(2):delivery.digest(self.db,[article],Mock(return_value=directory),send,sunday)
        send.assert_called_once();alert.assert_called_once()
    def test_unsigned_expired_and_tampered_unsubscribe_tokens_rejected(self):
        token=delivery.token_for('email|one');self.assertEqual(delivery.token_subject(token),'email|one')
        with self.assertRaises(ValueError):delivery.token_subject(token+'a')
        with patch.object(delivery.time,'time',return_value=0):expired=delivery.token_for('email|one')
        with self.assertRaises(ValueError):delivery.token_subject(expired)
        self.assertEqual(self.client.post('/insights/unsubscribe?token=forged').status_code,400)
    def test_unsubscribe_get_does_not_mutate_and_post_updates_auth0(self):
        token=delivery.token_for('email|one')
        with patch.object(delivery,'Directory') as factory:
            self.assertEqual(self.client.get('/insights/unsubscribe',params={'token':token}).status_code,200);factory.assert_not_called()
            response=self.client.post('/insights/unsubscribe',data={'token':token})
            self.assertEqual(response.status_code,200);factory.return_value.unsubscribe.assert_called_once_with('email|one')
    def test_push_claims_dedupe_and_do_not_replay_history(self):
        subscription=self.subscription();delivery.subscribe_push(self.db,subscription,'test-client')
        created=datetime.now(timezone.utc)
        articles=[{'id':'old','title':'Old','published_at':(created-timedelta(days=2)).isoformat()},
                  {'id':'new','title':'New','published_at':(created+timedelta(seconds=1)).isoformat()}]
        send=Mock()
        delivery.pushes(self.db,articles,send);delivery.pushes(self.db,articles,send)
        send.assert_called_once();self.assertEqual(send.call_args.args[1]['id'],'new')
    def test_ses_message_includes_one_click_unsubscribe_and_no_sdk_retries(self):
        with patch('boto3.client') as client:
            delivery.send_digest(self.user(),[{'title':'Title','summary':'Summary','url':'https://bun2too.com/insights/one'}])
        self.assertEqual(client.call_args.kwargs['config'].retries['total_max_attempts'],1)
        from email import message_from_bytes
        message=message_from_bytes(client.return_value.send_email.call_args.kwargs['Content']['Raw']['Data'])
        self.assertEqual(message['List-Unsubscribe-Post'],'List-Unsubscribe=One-Click')
        self.assertIn('/insights/unsubscribe?token=',message['List-Unsubscribe'])
        self.assertEqual(message['To'],'reader@example.com')
