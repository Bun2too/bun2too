import asyncio
import fcntl
import threading
from contextlib import asynccontextmanager
import html
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .crews import build_crew
from .models import ApprovalRequest, CampaignRequest, GenerationRequest, MarketingArtifact, LessonRequest
from .store import Store, now
from .observability import redact, workflow_span
from . import atlassian, marketing, telemetry

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parents[1] / ".data")))
os.environ.setdefault("CREWAI_STORAGE_DIR", str((DATA_DIR / "crewai").resolve()))
logger = logging.getLogger(__name__)
worker_ready = threading.Event()
@asynccontextmanager
async def lifespan(app):
    stop = threading.Event()
    worker = None
    if os.getenv('WORKER_ENABLED', 'true').lower() == 'true':
        worker = threading.Thread(target=worker_loop, args=(stop,), daemon=True)
        worker.start()
    yield
    stop.set()
    if worker:
        await asyncio.to_thread(worker.join, 5)
    worker_ready.clear()


app = FastAPI(title="bun2too Marketing Department API", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False)


def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    key = os.getenv("MARKETING_API_KEY", "")
    if not key:
        raise HTTPException(503, "MARKETING_API_KEY is not configured")
    if not credentials or not secrets.compare_digest(credentials.credentials, key):
        raise HTTPException(401, "Invalid API key", headers={"WWW-Authenticate": "Bearer"})


def store():
    return Store(DATA_DIR / "runs.sqlite3")


def get_run(run_id):
    try:
        return store().get(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None


def change_run(run_id, **changes):
    try:
        return store().update(run_id, **changes)
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


def execute_run(run_id, social_only=False):
    db = store()
    try:
        previous = db.get(run_id)
        run = db.update(run_id, expected={"queued"}, status="running", attempts=previous.get('attempts', 0) + 1)
    except ValueError:
        return  # Another local dispatcher claimed the durable job.
    db.event(run_id, "run_started", operation="Crew.kickoff", model=os.getenv("LLM_MODEL"))
    try:
        def record_task(role, output, structured=None):
            task_id = run_id + ":" + role
            db.update(run_id, task=redact(dict(task_id=task_id, agent=role, completed_at=now(),
                                             output=output, structured=structured)))
            db.event(run_id, "task_completed", agent=role, task_id=task_id)
            logger.info("run=%s completed_agent=%s", run_id, role)

        brief = dict(run["brief"])
        if run.get('scheduled'):
            # Recheck queued jobs too: delivery may have been disabled since creation.
            marketing.delivery_config()
            config = marketing.profile()
            sources = marketing.source_context(config)
            db.update(run_id, source_snapshots=sources)
            brief['source_material'] = json.dumps({'business_facts': config['business_facts'], 'sources': sources})
            brief['observed_results'] = db.feedback_context()
            brief['retrospective_instruction'] = ('Compare observed post results, distinguish missing metrics from zero, '
                'propose one evidence-backed improvement for this cycle; do not claim causality or invented results.')
            brief['required_output'] = 'Exactly one original article in articles and one Facebook post linking to it.'
            brief['publishing_rules'] = {'forbidden_phrases': config.get('forbidden_phrases', []),
                                        'links': 'No URLs in prose. Put retrieved citations in article.source_urls.'}
            db.event(run_id, 'research_collected', source_urls=[item['url'] for item in sources])
        previous_publications = db.publications(run_id)
        brief["existing_campaign_backlog"] = [
            {"work_key": p["content"].get("work_key"), "title": p["content"].get("title"), "reference": p["remote"]}
            for p in previous_publications if p["kind"] in {"story", "task"}]
        brief["jira_issue_keys"] = list(dict.fromkeys(
            brief.get("jira_issue_keys", []) +
            [p["remote"]["key"] for p in previous_publications
             if p["remote"] and p["kind"] in {"epic", "story", "task"}]))[:40]
        brief["referenced_work"] = atlassian.load_references(brief)
        brief["reviewed_lessons"] = []
        for previous_id in brief.get("lesson_run_ids", []):
            db.get(previous_id)
            brief["reviewed_lessons"].extend(
                dict(source_run_id=previous_id, **event) for event in db.events(previous_id)
                if event["kind"] == "lesson_reviewed")
        if len(json.dumps(brief["reviewed_lessons"])) > 60000:
            raise ValueError("Too many reviewed lessons selected")
        db.event(run_id, "context_loaded", jira_issue_keys=brief.get("jira_issue_keys", []),
                 confluence_page_ids=brief.get("confluence_page_ids", []),
                 lesson_run_ids=brief.get("lesson_run_ids", []))
        with workflow_span(run_id):
            crew = build_crew(brief, record_task, social_only=social_only,
                              record_event=lambda kind, **data: db.event(run_id, kind, **data))
            result = crew.kickoff()
        artifact = (MarketingArtifact.model_validate(result.pydantic) if result.pydantic
                    else MarketingArtifact.model_validate_json(result.raw))
        allowed = {channel.lower() for channel in run["brief"]["channels"]}
        if any(post.channel.lower() not in allowed for post in artifact.posts):
            raise ValueError("Artifact contains an unrequested channel")
        db.update(run_id, status="awaiting_review", artifact=artifact.model_dump())
        db.event(run_id, "run_completed", status="awaiting_review")
        if run.get('scheduled'):
            config = marketing.profile()
            try:
                marketing.check_artifact(db.get(run_id), config)
            except ValueError as exc:
                db.event(run_id, 'automatic_approval_blocked', reason=str(exc))
            else:
                if config.get('approval_mode') == 'automatic' and os.getenv('AUTO_APPROVAL_ENABLED', 'false').lower() == 'true':
                    approve(run_id, ApprovalRequest(reviewer='configured-automatic-policy'))
        if brief.get("campaign_key") and not run.get('scheduled'):
            try:
                atlassian.queue_campaign(db, run_id)
                if os.getenv("ATLASSIAN_AUTO_PUBLISH", "true").lower() in {"true", "1"}:
                    atlassian.publish_pending(db, run_id)
            except Exception as exc:
                db.event(run_id, "atlassian_sync_failed", error_type=type(exc).__name__,
                         message=str(exc) if isinstance(exc, ValueError) else "Inspect publication status")
        else:
            db.event(run_id, "atlassian_not_published", reason="Set campaign_key for automatic campaign publishing")
    except Exception as exc:
        # Provider errors can contain credentials or private prompts; do not expose them.
        logger.error("run=%s generation_failed type=%s", run_id, type(exc).__name__)
        db.update(run_id, status="failed", error="Generation failed (" + type(exc).__name__ + ")")
        db.event(run_id, "run_failed", error_type=type(exc).__name__)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/campaigns", status_code=202, dependencies=[Depends(authorize)])
def create_campaign(payload: CampaignRequest, background: BackgroundTasks):
    if not os.getenv("LLM_MODEL"):
        raise HTTPException(503, "LLM_MODEL is not configured")
    try:
        run = store().create(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    background.add_task(execute_run, run["id"])
    return {"run_id": run["id"], "status": run["status"], "review_url": "/runs/" + run["id"]}


@app.post("/generate-post", dependencies=[Depends(authorize)])
def generate_post(payload: GenerationRequest):
    if not os.getenv("LLM_MODEL"):
        raise HTTPException(503, "LLM_MODEL is not configured")
    brief = CampaignRequest(brief="Create one Facebook post. " + payload.topic_context,
                            source_material=payload.article_text)
    run = store().create(brief.model_dump())
    execute_run(run["id"], social_only=True)
    result = get_run(run["id"])
    if result["status"] == "failed":
        raise HTTPException(502, {"run_id": run["id"], "error": result["error"]})
    return {"status": "success", "run_id": run["id"],
            "generated_post": result["artifact"]["posts"][0]["text"]}


@app.get("/runs", dependencies=[Depends(authorize)])
def list_runs():
    return store().recent()


@app.get("/runs/{run_id}", dependencies=[Depends(authorize)])
def read_run(run_id: str):
    return get_run(run_id)


@app.get("/runs/{run_id}/work", dependencies=[Depends(authorize)])
def read_work(run_id: str):
    get_run(run_id)
    return {"events": store().events(run_id), "publications": store().publications(run_id)}


@app.post("/runs/{run_id}/lessons", dependencies=[Depends(authorize)])
def add_lesson(run_id: str, payload: LessonRequest):
    run = get_run(run_id)
    if run["status"] in {"queued", "running"}:
        raise HTTPException(409, "Wait for the run to finish before recording a reviewed lesson")
    store().event(run_id, "lesson_reviewed", **payload.model_dump())
    return {"status": "recorded", "source_run_id": run_id}


def publication_operation(operation):
    try:
        return operation()
    except KeyError:
        raise HTTPException(404, "Publication not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except Exception:
        raise HTTPException(502, "Atlassian operation failed; inspect saved publication status") from None


@app.get("/integrations/atlassian/check", dependencies=[Depends(authorize)])
def check_atlassian():
    return publication_operation(atlassian.check_connection)


@app.post("/runs/{run_id}/atlassian/publish", dependencies=[Depends(authorize)])
def publish_work(run_id: str):
    get_run(run_id)
    def publish():
        if get_run(run_id)["artifact"] is None:
            raise ValueError("Wait for a complete campaign artifact before publishing")
        atlassian.queue_campaign(store(), run_id)
        return atlassian.publish_pending(store(), run_id)
    return publication_operation(publish)


@app.post("/publications/{publication_id}/retry", dependencies=[Depends(authorize)])
def retry_publication(publication_id: str):
    def retry():
        store().update_publication(publication_id, {"failed"}, status="pending", error=None)
        return atlassian.publish_one(store(), publication_id)
    return publication_operation(retry)


class ReconcileRequest(BaseModel):
    remote_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9-]+$")


@app.post("/publications/{publication_id}/reconcile", dependencies=[Depends(authorize)])
def reconcile_publication(publication_id: str, payload: ReconcileRequest):
    return publication_operation(lambda: atlassian.reconcile(store(), publication_id, payload.remote_id))


@app.post("/runs/{run_id}/approve", dependencies=[Depends(authorize)])
def approve(run_id: str, payload: ApprovalRequest):
    run = get_run(run_id)
    if run["status"] != "awaiting_review":
        raise HTTPException(409, "Run must be awaiting_review")
    artifact = payload.artifact or MarketingArtifact.model_validate(run["artifact"])
    if artifact.blockers:
        raise HTTPException(409, "Resolve blockers in an edited artifact before approving")
    allowed = {channel.lower() for channel in run["brief"]["channels"]}
    if any(post.channel.lower() not in allowed for post in artifact.posts):
        raise HTTPException(422, "Posts must use the requested channels")
    digest = hashlib.sha256(json.dumps(artifact.model_dump(), sort_keys=True).encode()).hexdigest()
    result = change_run(run_id, expected={"awaiting_review"}, status="approved",
                      artifact=artifact.model_dump(),
                      approval=dict(reviewer=payload.reviewer, approved_at=now(), sha256=digest))
    store().event(run_id, "social_content_approved", reviewer=payload.reviewer, sha256=digest)
    return result


@app.post("/runs/{run_id}/dispatch", dependencies=[Depends(authorize)])
def dispatch(run_id: str):
    if os.getenv("PUBLISHING_ENABLED", "false").lower() != "true":
        raise HTTPException(403, "Publishing handoff is disabled")
    url = os.getenv("N8N_WEBHOOK_URL", "")
    token = os.getenv("N8N_WEBHOOK_TOKEN", "")
    if urlsplit(url).scheme != "https" or not urlsplit(url).hostname or not token:
        raise HTTPException(503, "Configure an HTTPS N8N_WEBHOOK_URL and N8N_WEBHOOK_TOKEN")
    # Claim atomically; never auto-retry ambiguous network failures.
    run = change_run(run_id, expected={"approved"}, status="dispatching")
    store().event(run_id, "social_dispatch_requested", operation="POST n8n webhook", host=urlsplit(url).hostname)
    try:
        response = httpx.post(url, headers={"Authorization": "Bearer " + token,
                                           "Idempotency-Key": run_id},
                              json={"run_id": run_id, "artifact": run["artifact"],
                                    "approval": run["approval"]},
                              timeout=30, follow_redirects=False)
        response.raise_for_status()
    except Exception as exc:
        change_run(run_id, status="dispatch_unknown",
                   error="Check n8n executions before any manual retry (" + type(exc).__name__ + ")")
        raise HTTPException(502, "Dispatch outcome unknown; inspect n8n executions") from None
    return change_run(run_id, status="submitted", submitted_at=now())


def worker_loop(stop):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # One worker per mounted data directory, including overlapping processes during restart.
    with open(DATA_DIR / 'worker.lock', 'a') as lock:
        while not stop.is_set():
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                stop.wait(2)
        if stop.is_set():
            return
        store().recover_generation()
        worker_ready.set()
        while not stop.is_set():
            try:
                for run in store().queued():
                    if stop.is_set():
                        break
                    execute_run(run['id'])
                telemetry.flush(store())
            except Exception as exc:
                logger.error('worker_error type=%s', type(exc).__name__)
            stop.wait(2)


@app.get('/ready', dependencies=[Depends(authorize)])
def readiness():
    db = store()
    missing = []
    configuration_errors = {}
    if os.getenv('MARKETING_AUTOMATION_ENABLED', 'false').lower() == 'true':
        try:
            marketing.profile()
        except marketing.ProfileError as exc:
            missing.append('marketing_profile')
            configuration_errors['marketing_profile'] = str(exc)
        except (ValueError, OSError):
            missing.append('marketing_profile')
            configuration_errors['marketing_profile'] = 'Invalid marketing profile settings in config/marketing.json or MARKETING_PROFILE_PATH'
        try:
            marketing.delivery_config()
        except ValueError:
            missing.append('scheduled_facebook_delivery_configuration')
    if os.getenv('PUBLISHING_ENABLED', 'false').lower() == 'true':
        for key in ('FACEBOOK_GRAPH_VERSION', 'FACEBOOK_PAGE_ID', 'FACEBOOK_PAGE_ACCESS_TOKEN', 'PUBLIC_API_BASE_URL'):
            if not os.getenv(key):
                missing.append(key)
        try:
            marketing.graph_config()
        except ValueError:
            missing.append('valid_facebook_configuration')
        base = urlsplit(os.getenv('PUBLIC_API_BASE_URL', ''))
        if base.scheme != 'https' or not base.hostname or base.username or base.password:
            missing.append('valid_public_article_url')
    if os.getenv('DD_LOGS_ENABLED', 'false').lower() == 'true' and not os.getenv('DD_API_KEY'):
        missing.append('DD_API_KEY')
    return {'storage': 'ok', 'model_configured': bool(os.getenv('LLM_MODEL')),
            'configuration_errors': configuration_errors,
            'worker_ready': worker_ready.is_set(), 'missing_configuration': missing,
            'publishing_enabled': os.getenv('PUBLISHING_ENABLED', 'false'),
            'automation_enabled': os.getenv('MARKETING_AUTOMATION_ENABLED', 'false'),
            'queued_runs': len(db.queued())}


@app.post('/automation/tick', dependencies=[Depends(authorize)])
def automation_tick():
    if os.getenv('MARKETING_AUTOMATION_ENABLED', 'false').lower() != 'true':
        raise HTTPException(409, 'Scheduled marketing is disabled')
    try:
        config = marketing.profile()
        marketing.delivery_config()
        if not os.getenv('LLM_MODEL'):
            raise ValueError('LLM_MODEL is not configured')
        slot = marketing.schedule_slot(config)
        if slot is None:
            return {'status': 'not_due'}
        brief = CampaignRequest(campaign_key=config['campaign_key'], brief=config['brief'], audience=config['audience'],
                                channels=['facebook'], brand_guidelines=config.get('brand_guidelines', ''),
                                source_material=config['business_facts']).model_dump()
        after, before = marketing.publication_window(config)
        run, created = store().schedule(config['campaign_key'] + ':' + slot, brief,
                                       publish_after=after.isoformat(), publish_before=before.isoformat())
        if created:
            store().event(run['id'], 'scheduled_run_created', slot=slot)
        return {'status': run['status'], 'run_id': run['id'], 'created': created}
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Marketing profile unavailable') from None


@app.post('/automation/publish', dependencies=[Depends(authorize)])
def automation_publish():
    results = []
    for candidate in store().recent():
        run = store().get(candidate['id'])
        if run['status'] == 'approved' and run.get('scheduled'):
            try:
                results.append(marketing.publish_one(store(), run['id']))
            except ValueError as exc:
                results.append({'run_id': run['id'], 'status': 'blocked', 'reason': str(exc)})
                if str(exc) != 'Publication is not due yet' and run.get('publication_blocker') != str(exc):
                    store().update(run['id'], publication_blocker=str(exc))
                    store().event(run['id'], 'facebook_publication_blocked', status='blocked', reason=str(exc))
    return {'publications': results}


@app.post('/automation/metrics', dependencies=[Depends(authorize)])
def automation_metrics():
    try:
        return {'results': marketing.collect_metrics(store())}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.get('/automation/status', dependencies=[Depends(authorize)])
def automation_status():
    return {'runs': store().recent(), 'publications': store().social_recent()}


class ReconcilePost(BaseModel):
    remote_id: str = Field(pattern=r'^\d+_\d+$')
    reviewer: str = Field(min_length=1, max_length=200)


@app.post('/social-publications/{publication_id}/reconcile', dependencies=[Depends(authorize)])
def reconcile_post(publication_id: str, payload: ReconcilePost):
    try:
        db = store()
        record = db.social(publication_id)
        version, page, token = marketing.graph_config()
        if record['page_id'] != page or not payload.remote_id.startswith(page + '_'):
            raise ValueError('Post belongs to a different configured Page')
        response = httpx.get(f'https://graph.facebook.com/{version}/{payload.remote_id}',
                             params={'fields': 'id,message'}, headers={'Authorization': 'Bearer ' + token}, timeout=20)
        response.raise_for_status()
        observed = response.json()
        artifact = db.get(record['run_id'])['artifact']
        if observed.get('id') != payload.remote_id or observed.get('message') != artifact['posts'][0]['text']:
            raise ValueError('Facebook post does not match the approved content')
        result = db.finish_social(publication_id, 'published', expected=('sending', 'unknown'),
                                  remote_id=payload.remote_id, reconciled_by=payload.reviewer)
        db.event(record['run_id'], 'facebook_publication_reconciled', remote_id=payload.remote_id)
        return result
    except KeyError:
        raise HTTPException(404, 'Publication not found') from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except httpx.HTTPError:
        raise HTTPException(502, 'Cannot verify post with Facebook') from None


@app.get('/articles/{run_id}', response_class=HTMLResponse)
def article(run_id: str):
    run = get_run(run_id)
    if run['status'] not in {'publishing', 'published', 'publication_unknown', 'publication_failed'} or not run.get('approval'):
        raise HTTPException(404, 'Article not published')
    articles = (run.get('artifact') or {}).get('articles', [])
    if not articles:
        raise HTTPException(404, 'Article not found')
    content = articles[0]
    title = html.escape(content['title'])
    body = ''.join('<p>' + html.escape(p) + '</p>' for p in content['body'].split('\n\n'))
    sources = ''.join('<li><a rel="noopener noreferrer" href="' + html.escape(url, quote=True) + '">' +
                      html.escape(url) + '</a></li>' for url in content.get('source_urls', []) if urlsplit(url).scheme == 'https')
    if sources:
        body += '<h2>Sources</h2><ul>' + sources + '</ul>'
    return HTMLResponse('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" '
                        'content="width=device-width,initial-scale=1"><title>' + title + '</title></head>'
                        '<body><main><h1>' + title + '</h1>' + body + '</main></body></html>',
                        headers={'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'"})


class WorkflowEvent(BaseModel):
    execution_id: str = Field(max_length=100)
    workflow_name: str = Field(max_length=200)
    status: str = Field(pattern=r'^(failed|started|completed)$')


@app.post('/automation/events', dependencies=[Depends(authorize)])
def workflow_event(payload: WorkflowEvent):
    store().event('n8n:' + payload.execution_id, 'n8n_execution_' + payload.status,
                  workflow_name=payload.workflow_name, status=payload.status)
    return {'recorded': True}
