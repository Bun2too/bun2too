"""Opt-in insight delivery: Auth0 consent, SES weekly digest, browser Web Push.

Delivery claims survive restart. Ambiguous sends are not automatically replayed.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, quote
from zoneinfo import ZoneInfo
import httpx
from . import insights, notifications


def enabled(name): return os.getenv(name, 'false').lower() == 'true'


def initialize(db):
    with db.connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS insights_push (id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS insights_deliveries (id TEXT PRIMARY KEY, status TEXT NOT NULL, at TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS insights_rate (id TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL)')


def now(): return datetime.now(timezone.utc).isoformat()


def claim(db, key):
    with db.connect() as conn:
        result=conn.execute('INSERT OR IGNORE INTO insights_deliveries VALUES (?, ?, ?)',(key,'sending',now()))
        return result.rowcount == 1


def finish(db, key, status):
    with db.connect() as conn: conn.execute('UPDATE insights_deliveries SET status=?, at=? WHERE id=?',(status,now(),key))


def validate_subscription(value):
    if not isinstance(value,dict): raise ValueError('Invalid push subscription')
    endpoint=value.get('endpoint','')
    if not isinstance(endpoint,str) or len(endpoint)>2048: raise ValueError('Invalid push endpoint')
    parsed=urlsplit(endpoint); host=parsed.hostname or ''
    allowed=host in {'fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com'} or host.endswith('.push.services.mozilla.com') or host.endswith('.notify.windows.com')
    if not allowed or parsed.scheme!='https' or parsed.port not in {None,443} or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Unsupported browser push service')
    keys=value.get('keys') or {}
    if not isinstance(keys,dict): raise ValueError('Invalid push keys')
    for name,length in [('p256dh',65),('auth',16)]:
        key=keys.get(name,'')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}',key): raise ValueError('Invalid push keys')
        try: decoded=base64.urlsafe_b64decode(key+'='*(-len(key)%4))
        except Exception: raise ValueError('Invalid push keys') from None
        if len(decoded)!=length: raise ValueError('Invalid push keys')
    return {'endpoint':endpoint,'keys':{k:keys[k] for k in ['p256dh','auth']}}


def subscribe_push(db, subscription, address):
    initialize(db);subscription=validate_subscription(subscription)
    key=hashlib.sha256(subscription['endpoint'].encode()).hexdigest()
    bucket=hashlib.sha256((address+':'+str(int(time.time())//3600)).encode()).hexdigest()
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM insights_rate WHERE expires < ?', (int(time.time()),))
        conn.execute('INSERT OR IGNORE INTO insights_rate VALUES (?,0,?)',(bucket,int(time.time())+3600))
        count=conn.execute('SELECT count FROM insights_rate WHERE id=?',(bucket,)).fetchone()[0]
        if count>=20: raise ValueError('Too many subscription requests; try again later')
        conn.execute('UPDATE insights_rate SET count=count+1 WHERE id=?',(bucket,))
        if conn.execute('SELECT count(*) FROM insights_push').fetchone()[0]>=10000 and not conn.execute('SELECT 1 FROM insights_push WHERE id=?',(key,)).fetchone():
            raise ValueError('Push registration capacity reached')
        # Re-registering an endpoint must not change encryption keys or replay history.
        conn.execute('INSERT OR IGNORE INTO insights_push VALUES (?,?,?)',(key,json.dumps(subscription),now()))


class Directory:
    def __init__(self):
        domain=os.environ['AUTH0_DOMAIN']
        if not re.fullmatch(r'[A-Za-z0-9.-]+',domain): raise ValueError('Invalid Auth0 domain')
        self.base='https://'+domain
        self.client=httpx.Client(timeout=15,follow_redirects=False)
        result=self.client.post(self.base+'/oauth/token',json={'grant_type':'client_credentials',
            'client_id':os.environ['AUTH0_MANAGEMENT_CLIENT_ID'],'client_secret':os.environ['AUTH0_MANAGEMENT_CLIENT_SECRET'],
            'audience':self.base+'/api/v2/'})
        result.raise_for_status();self.headers={'Authorization':'Bearer '+result.json()['access_token']}
    def close(self): self.client.close()
    def get(self, path, **kwargs):
        result=self.client.get(self.base+'/api/v2/'+path,headers=self.headers,**kwargs);result.raise_for_status();return result.json()
    def user(self, subject): return self.get('users/'+quote(subject,safe=''))
    def subscribers(self):
        # Search is eventually consistent. Re-read each user by ID before sending.
        users=[]
        for page in range(10):
            result=self.get('users',params={'q':'app_metadata.bun2too.newsletter.status:"subscribed"',
                'search_engine':'v3','page':page,'per_page':100,'include_totals':'true'})
            if result.get('total',0)>=1000: raise ValueError('Subscriber search limit reached; configure an export-based audience')
            users.extend(result['users'])
            if len(users)>=result['total']: return users
        return users
    def unsubscribe(self, subject):
        user=self.user(subject);metadata=user.get('app_metadata') or {};namespace=metadata.get('bun2too') or {}
        previous=namespace.get('newsletter') or {}
        namespace['newsletter']={**previous,'status':'unsubscribed','withdrawn_at':now(),'updated_at':now(),'source':'insights-unsubscribe'}
        metadata['bun2too']=namespace
        response=self.client.patch(self.base+'/api/v2/users/'+quote(subject,safe=''),headers=self.headers,json={'app_metadata':metadata})
        response.raise_for_status()


def eligible(user):
    preference=((user.get('app_metadata') or {}).get('bun2too') or {}).get('newsletter') or {}
    email=user.get('email','')
    return (user.get('email_verified') is True and preference.get('status')=='subscribed'
            and 'ai-automation' in preference.get('topics',[]) and isinstance(email,str)
            and re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email) is not None)


def token_for(subject):
    secret=os.environ['INSIGHTS_UNSUBSCRIBE_SECRET']
    if len(secret)<32: raise ValueError('Configure a strong unsubscribe signing secret')
    raw=base64.urlsafe_b64encode(json.dumps({'sub':subject,'exp':int(time.time())+366*86400}).encode()).decode().rstrip('=')
    signature=hmac.new(secret.encode(),raw.encode(),hashlib.sha256).hexdigest()
    return raw+'.'+signature


def token_subject(token):
    if not isinstance(token,str) or len(token)>2048: raise ValueError('Invalid unsubscribe link')
    try:
        raw,signature=token.split('.')
        expected=hmac.new(os.environ['INSIGHTS_UNSUBSCRIBE_SECRET'].encode(),raw.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature): raise ValueError()
        data=json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
        if data['exp']<time.time() or not isinstance(data['sub'],str): raise ValueError()
        return data['sub']
    except Exception: raise ValueError('Invalid or expired unsubscribe link; use your account preferences') from None


def send_digest(user, articles):
    import boto3
    from botocore.config import Config
    from email.message import EmailMessage
    from email.policy import SMTP
    link=insights.site_url()+'/insights/unsubscribe?token='+token_for(user['user_id'])
    message=EmailMessage(policy=SMTP.clone(max_line_length=998));message['From']=os.environ['INSIGHTS_EMAIL_FROM'];message['To']=user['email']
    message['Subject']='Your week in Bun2Too Insights'
    message['List-Unsubscribe']='<'+link+'>';message['List-Unsubscribe-Post']='List-Unsubscribe=One-Click'
    message.set_content('Ideas worth connecting. Your weekly Bun2Too reading list.\n\n'+'\n\n'.join(
        a['title']+'\n'+a['summary']+'\n'+a['url'] for a in articles)+'\n\nUnsubscribe: '+link+
        '\nManage topics: '+insights.site_url()+'/account\n')
    client=boto3.client('sesv2',region_name=os.getenv('AWS_REGION','us-west-2'),config=Config(connect_timeout=10,read_timeout=20,retries={'total_max_attempts':1}))
    client.send_email(FromEmailAddress=os.environ['INSIGHTS_EMAIL_FROM'],Destination={'ToAddresses':[user['email']]},Content={'Raw':{'Data':message.as_bytes()}})


def digest(db, articles, directory_factory=Directory, send=send_digest, instant=None):
    instant=instant or datetime.now(timezone.utc)
    local=instant.astimezone(ZoneInfo('America/Chicago'))
    if local.weekday()!=6 or local.hour<9: return
    recent=[a for a in articles if datetime.fromisoformat(a['published_at'])>=instant-timedelta(days=7)]
    if not recent: return
    week=local.strftime('%G-%V')
    # Validate before making claims; configuration errors must not consume recipients.
    token_for('configuration-check');os.environ['INSIGHTS_EMAIL_FROM']
    directory=directory_factory()
    try:
        seen=set()
        for candidate in directory.subscribers():
            user=directory.user(candidate['user_id'])
            if not eligible(user): continue
            email=user['email'].lower()
            if email in seen: continue
            seen.add(email)
            key='digest:'+week+':'+hashlib.sha256(email.encode()).hexdigest()
            if not claim(db,key): continue
            try: send(user,recent);finish(db,key,'sent')
            except Exception:
                finish(db,key,'unknown')
                notifications.incident(db,'insights:digest-delivery','Insight digest delivery needs inspection',
                    'An SES request failed or its outcome is uncertain. Inspect delivery records before replay; subscriber details are not logged.')
    finally: directory.close()


def send_push(subscription, article):
    from pywebpush import webpush
    import requests
    session=requests.Session();session.max_redirects=0
    try:
        return webpush(subscription_info=subscription,data=json.dumps({'id':article['id'],'title':article['title'],'path':'/insights/'+article['id']}),
            vapid_private_key=os.environ['INSIGHTS_VAPID_PRIVATE_KEY'],vapid_claims={'sub':os.environ['INSIGHTS_VAPID_SUBJECT']},
            ttl=3600,timeout=15,requests_session=session)
    finally: session.close()


def pushes(db, articles, send=send_push):
    cutoff=datetime.now(timezone.utc)-timedelta(days=1)
    with db.connect() as conn: subscriptions=conn.execute('SELECT id,data,created_at FROM insights_push').fetchall()
    for article in articles:
        if datetime.fromisoformat(article['published_at'])<cutoff: continue
        for key,data,created in subscriptions:
            if created>=article['published_at']: continue
            delivery='push:'+article['id']+':'+key
            if not claim(db,delivery): continue
            try: send(json.loads(data),article);finish(db,delivery,'sent')
            except Exception as exc:
                response=getattr(exc,'response',None)
                if response is not None and response.status_code in {404,410}:
                    with db.connect() as conn: conn.execute('DELETE FROM insights_push WHERE id=?',(key,))
                    finish(db,delivery,'expired')
                else:
                    finish(db,delivery,'unknown')
                    notifications.incident(db,'insights:push-delivery','Browser notification delivery needs inspection',
                        'A push request failed or its outcome is uncertain. Check VAPID configuration and delivery records.')


def loop(stop, db, data_dir):
    initialize(db);last_digest=None
    while not stop.is_set():
        try:
            articles=insights.entries(db,data_dir)
            if enabled('INSIGHTS_PUSH_ENABLED'): pushes(db,articles)
            if enabled('INSIGHTS_DIGEST_ENABLED') and (last_digest is None or time.monotonic()-last_digest>=3600):
                last_digest=time.monotonic();digest(db,articles)
        except Exception as exc:
            # Provider errors may contain recipient addresses and credentials.
            notifications.incident(db,'insights:delivery-worker','Insight notification worker failed',
                                  'Inspect notification configuration; error type: '+type(exc).__name__)
        stop.wait(60)
