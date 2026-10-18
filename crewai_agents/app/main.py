import asyncio
import fcntl
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .crews import build_crew, generation_settings
from .models import ApprovalRequest, CampaignRequest, GenerationRequest, MarketingArtifact, LessonRequest
from .store import Store, now
from .observability import redact, workflow_span, error_details, trace_context
from . import article_view, atlassian, marketing, telemetry, otel, ai_telemetry, evaluation, langsmith_trace, recovery, operations, notifications

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parents[1] / ".data")))
os.environ.setdefault("CREWAI_STORAGE_DIR", str((DATA_DIR / "crewai").resolve()))
logger = logging.getLogger(__name__)
worker_ready = threading.Event()
@asynccontextmanager
async def lifespan(app):
    otel.initialize()
    stop = threading.Event()
    export_stop = threading.Event()
    exporter = threading.Thread(target=telemetry.export_loop, args=(export_stop, store()), daemon=True, name='telemetry-export')
    exporter.start()
    otel.runtime_metrics(store(), DATA_DIR, worker_ready)
    operations_stop = threading.Event()
    operations_worker = None
    if os.getenv('OPERATIONS_ENABLED', 'false').lower() == 'true':
        operations.bootstrap(store())
        operations_worker = threading.Thread(target=operations.loop, args=(operations_stop, store()), daemon=True, name='operations-watchdog')
        operations_worker.start()
    worker = None
    if os.getenv('WORKER_ENABLED', 'true').lower() == 'true':
        worker = threading.Thread(target=worker_loop, args=(stop,), daemon=True)
        worker.start()
    try:
        yield
    finally:
        stop.set()
        if worker:
            await asyncio.to_thread(worker.join, 5)
        worker_ready.clear()
        operations_stop.set()
        if operations_worker:
            await asyncio.to_thread(operations_worker.join, 35)
        export_stop.set()
        await asyncio.to_thread(exporter.join, 16)
        await asyncio.to_thread(otel.shutdown)
        await asyncio.to_thread(langsmith_trace.flush)


app = FastAPI(title="bun2too Marketing Department API", lifespan=lifespan)
app.add_middleware(otel.RequestTracing)
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
    run = db.get(run_id)
    if run.get('scheduled') and operations.circuit(db):
        return
    if run.get('scheduled') and run.get('publish_before') and datetime.fromisoformat(run['publish_before']) <= datetime.now(timezone.utc):
        if run['status'] == 'queued':
            db.update(run_id, expected={'queued'}, status='expired', publication_blocker='Publishing window expired before generation.')
        return
    token = otel.RUN.set({'id': run_id, 'db': db})
    try:
        with otel.span('campaign.run', {'run.id': run_id, 'run.attempt': run.get('attempts', 0) + 1},
                       linked=run.get('trace_context') or None) as current, workflow_span(run_id):
            _execute_run(run_id, social_only)
            result = db.get(run_id)
            current.set_attribute('run.outcome', result['status'])
            if result['status'] == 'failed':
                current.set_status(otel.Status(otel.StatusCode.ERROR))
    finally:
        otel.RUN.reset(token)


def _execute_run(run_id, social_only=False):
    db = store()
    try:
        previous = db.get(run_id)
        run = db.update(run_id, expected={"queued"}, status="running", attempts=previous.get('attempts', 0) + 1,
                        execution_trace=otel.carrier())
    except ValueError:
        return  # Another local dispatcher claimed the durable job.
    started = time.monotonic()
    operation = 'load_context'
    correlation = {}
    context = dict(campaign_key=run.get('campaign_key'), model=os.getenv('LLM_MODEL'), attempt=run['attempts'])
    db.event(run_id, "run_started", operation=operation, **context)
    if run.get("scheduled"):
        atlassian.sync_scheduled(db, run_id)
    try:
        def record_task(role, output, structured=None):
            task_id = run_id + ":" + str(run["attempts"]) + ":" + role
            db.update(run_id, task=redact(dict(task_id=task_id, agent=role, completed_at=now(),
                                             output=output, structured=structured)))
            db.event(run_id, "task_completed", agent=role, task_id=task_id, **context)
            langsmith_trace.event("agent_deliverable", dict(agent=role, **{key: (structured or {}).get(key)
                for key in ("summary", "decisions", "evidence")}))
            logger.info("run=%s completed_agent=%s", run_id, role)

        brief = dict(run["brief"])
        if run.get('scheduled'):
            # Recheck queued jobs too: delivery may have been disabled since creation.
            marketing.delivery_config()
            operation = 'facebook.preflight'
            destination = marketing.verify_delivery()
            db.event(run_id, 'facebook_delivery_verified', **destination)
            operation = 'load_context'
            config = marketing.profile()
            sources, source_failures = marketing.source_context(config)
            editorial = marketing.editorial_context(db, run, config)
            db.update(run_id, source_snapshots=sources, editorial_context=editorial)
            brief['editorial_context'] = editorial
            db.event(run_id, 'editorial_policy_selected', **editorial)
            brief['source_material'] = json.dumps({'business_facts': config['business_facts'],
                                                   'recent_research': sources})
            brief['observed_results'] = db.feedback_context()
            brief['retrospective_instruction'] = ('Compare observed post results, distinguish missing metrics from zero, '
                'propose one evidence-backed improvement for this cycle; do not claim causality or invented results.')
            brief['required_output'] = ('Follow editorial_context and select a source-supported topic. Produce exactly one '
                                        'original article in articles and one Facebook post linking to it.')
            brief['publishing_rules'] = {'forbidden_phrases': config.get('forbidden_phrases', []),
                                        'links': 'No URLs in prose. Put retrieved citations in article.source_urls.'}
            brief['publishing_context'] = {
                'scheduled': True,
                'approval_mode': config.get('approval_mode'),
                'automatic_approval_enabled': os.getenv('AUTO_APPROVAL_ENABLED', 'false').lower() == 'true',
                'page_id': destination.get('page_id'),
                'page_identity_verified': destination.get('status') == 'ready',
                'article_url': os.environ['PUBLIC_API_BASE_URL'].rstrip('/') + '/articles/' + run_id,
                'publish_after': run.get('publish_after'), 'publish_before': run.get('publish_before'),
                'review_scope': ('Review factual evidence, article and Facebook copy, brand rules and source citations. '
                    'The publisher adds article_url as Facebook link after approval; never insert it into prose. '
                    'The draft article endpoint is intentionally private before dispatch. '
                    'Do not require a live preview or prior post, analytics/infrastructure tests, images, '
                    'Jira tasks, or an extra human approval when automatic policy is enabled. '
                    'The application enforces release timing, approved-content hashing and duplicate-send protection. '
                    'Do not claim tests were run. Missing metrics are not content blockers. '
                    'Reject unsupported factual claims or rewrite them using the supplied sources.'),
            }
            db.event(run_id, 'research_collected', source_urls=[item['url'] for item in sources],
                     recent_item_count=sum(bool(item.get('published_at')) for item in sources),
                     feed_failures=source_failures)
        previous_publications = [] if run.get('scheduled') else db.publications(run_id)
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
        manifest = {'service_version': os.getenv('SERVICE_VERSION', 'unknown'),
                    'prompt_version': ai_telemetry.version([Path(__file__).with_name(name).read_text() for name in ('agents.json', 'crews.py')]),
                    'policy_version': ai_telemetry.version(marketing.profile()) if run.get('scheduled') else 'manual-v1',
                    'source_snapshot_hash': ai_telemetry.version(brief.get('source_material', ''))}
        db.update(run_id, telemetry_manifest=manifest)
        db.event(run_id, 'run_manifest', **manifest)
        db.event(run_id, "context_loaded", jira_issue_keys=brief.get("jira_issue_keys", []),
                 confluence_page_ids=brief.get("confluence_page_ids", []),
                 lesson_run_ids=brief.get("lesson_run_ids", []))
        with otel.span('crew.kickoff'):
            correlation = trace_context()
            operation = 'build_crew'
            settings = generation_settings()
            db.update(run_id, generation_settings=settings)
            db.event(run_id, 'generation_configured', **settings, attempt=run['attempts'])
            ai_telemetry.input_policy(brief)
            crew = build_crew(brief, record_task, social_only=social_only,
                              record_event=lambda kind, **data: db.event(run_id, kind, attempt=run["attempts"], **data))
            operation = 'Crew.kickoff'
            result = crew.kickoff()
        operation = 'validate_artifact'
        with otel.span('artifact.validate'):
            artifact = (MarketingArtifact.model_validate(result.pydantic) if result.pydantic
                        else MarketingArtifact.model_validate_json(result.raw))
        allowed = {channel.lower() for channel in run["brief"]["channels"]}
        if any(post.channel.lower() not in allowed for post in artifact.posts):
            raise ValueError("Artifact contains an unrequested channel")
        db.update(run_id, status="awaiting_review", artifact=artifact.model_dump())
        quality = ai_telemetry.quality(db.get(run_id))
        db.update(run_id, quality=quality)
        db.event(run_id, 'quality_evaluated', quality=quality, evaluator=quality['evaluator'])
        db.event(run_id, "run_completed", status="awaiting_review", duration_ms=round((time.monotonic() - started) * 1000))
        if run.get('scheduled'):
            config = marketing.profile()
            try:
                marketing.check_artifact(db.get(run_id), config)
            except ValueError as exc:
                db.update(run_id, publication_blocker=str(exc))
                db.event(run_id, 'automatic_approval_blocked', status='blocked', reason=str(exc), **context)
            else:
                artwork = create_article_artwork(db, run_id, artifact.model_dump())
                db.update(run_id, article_artwork=artwork)
                if config.get('approval_mode') == 'automatic' and os.getenv('AUTO_APPROVAL_ENABLED', 'false').lower() == 'true':
                    approve(run_id, ApprovalRequest(reviewer='configured-automatic-policy'))
                else:
                    reason = 'Automatic approval is disabled; content requires review'
                    db.update(run_id, publication_blocker=reason)
                    db.event(run_id, 'automatic_approval_blocked', status='blocked', reason=reason, **context)
        if brief.get("campaign_key") and not run.get('scheduled'):
            try:
                atlassian.queue_campaign(db, run_id)
                if os.getenv("ATLASSIAN_AUTO_PUBLISH", "true").lower() in {"true", "1"}:
                    atlassian.publish_pending(db, run_id)
            except Exception as exc:
                db.event(run_id, "atlassian_sync_failed", error_type=type(exc).__name__,
                         message=str(exc) if isinstance(exc, ValueError) else "Inspect publication status")
        elif not run.get('scheduled'):
            db.event(run_id, "atlassian_not_published", reason="Set campaign_key for automatic campaign publishing")
    except Exception as exc:
        diagnostic = error_details(exc)
        if operation == 'Crew.kickoff' and diagnostic['kind'] == 'TimeoutError':
            diagnostic['message'] = ('Generation exceeded its execution budget; '
                f"model request timeout={settings['request_timeout_seconds']}s, "
                f"agent timeout={settings['agent_timeout_seconds']}s, reasoning_effort={settings['reasoning_effort']}")
        policy = recovery.classify(diagnostic, run['attempts'])
        retryable = operation in {'Crew.kickoff', 'facebook.preflight', 'load_context'} and policy['retryable'] and run['attempts'] < 3
        retry_after = (datetime.now(timezone.utc) + timedelta(seconds=policy['delay_seconds'])).isoformat() if retryable else None
        reason = policy['reason'] if policy['category'] != 'generation_error' else 'Generation failed (' + diagnostic['kind'] + '); inspect run diagnostics.'
        if policy['retryable'] and run['attempts'] >= 3:
            reason = 'Automatic generation recovery exhausted after three attempts; inspect the provider and resume manually within the publishing window.'
        logger.error("run=%s operation=%s generation_failed %s", run_id, operation, json.dumps(diagnostic))
        db.update(run_id, status="failed", error=reason, failure_category=policy["category"],
                  error_details=diagnostic, retryable=retryable, retry_after=retry_after)
        operations.pause(db, run_id, policy)
        notifications.incident(db, "campaign:" + run_id, "Daily campaign generation failed", reason, run_id,
                               severity="critical" if policy["pause_generation"] or run["attempts"] >= 3 else "error")
        completed = [task['agent'] for task in db.get(run_id).get('tasks', [])]
        roles = ['researcher', 'writer', 'editor', 'delivery'] if social_only else [
            'product_owner', 'business_analyst', 'researcher', 'creative', 'writer', 'engineering', 'tester', 'editor', 'delivery']
        db.event(run_id, "run_failed", status='failed', error_type=type(exc).__name__, error=diagnostic,
                 operation=operation, agent=next((role for role in roles if role not in completed), None) if operation == 'Crew.kickoff' else None,
                 retryable=retryable, retry_after=retry_after,
                 duration_ms=round((time.monotonic() - started) * 1000), **context, **(trace_context() or correlation))

    finally:
        if run.get('scheduled'):
            atlassian.sync_scheduled(db, run_id)


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
    return {"events": store().events(run_id), "publications": store().publications(run_id),
            "agents": atlassian.agent_report(store(), run_id)}


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
        if get_run(run_id).get("scheduled"):
            atlassian.queue_scheduled(store(), run_id)
            return atlassian.publish_pending(store(), run_id)
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
@otel.observed('approval.review')
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
    if run.get("scheduled"):
        atlassian.sync_scheduled(store(), run_id)
    return result


@app.post("/runs/{run_id}/dispatch", dependencies=[Depends(authorize)])
@otel.observed('n8n.dispatch')
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
        store().event('runtime', 'runtime_started', status='ready')
        backfill_article_artwork(store())
        while not stop.is_set():
            try:
                for run in store().queued():
                    if stop.is_set():
                        break
                    execute_run(run['id'])
                notifications.resolve(store(), 'runtime:worker', 'Campaign worker loop is operating again.')
            except Exception as exc:
                diagnostic = error_details(exc)
                logger.error('worker_error %s', json.dumps(diagnostic))
                try:
                    store().event('runtime', 'worker_failed', status='failed', error=diagnostic)
                    notifications.incident(store(), 'runtime:worker', 'Campaign worker failed',
                                           'Inspect service logs and worker diagnostics; error type: ' + diagnostic['kind'])
                except Exception:
                    logger.error('Could not persist worker failure; inspect service logs')
            stop.wait(2)


@app.get('/ready', dependencies=[Depends(authorize)])
def readiness():
    db = store()
    missing = []
    configuration_errors = {}
    if os.getenv('MODEL_ROUTING_ENABLED', 'false').lower() == 'true':
        try:
            from . import model_routing
            settings = generation_settings()
            for role in model_routing.ROLES:
                model_routing.route(role, settings)
        except ValueError as exc:
            missing.append('model_routing')
            configuration_errors['model_routing'] = str(exc)
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
    if not otel.enabled() and os.getenv('DD_LOGS_ENABLED', 'false').lower() == 'true' and not os.getenv('DD_API_KEY'):
        missing.append('DD_API_KEY')
    return {'storage': 'ok', 'model_configured': bool(os.getenv('LLM_MODEL')),
            'configuration_errors': configuration_errors,
            'worker_ready': worker_ready.is_set(), 'missing_configuration': missing,
            'publishing_enabled': os.getenv('PUBLISHING_ENABLED', 'false'),
            'automation_enabled': os.getenv('MARKETING_AUTOMATION_ENABLED', 'false'),
            'queued_runs': len(db.queued())}


@app.post('/automation/tick', dependencies=[Depends(authorize)])
@otel.observed('scheduler.tick')
def automation_tick():
    if os.getenv('MARKETING_AUTOMATION_ENABLED', 'false').lower() != 'true':
        raise HTTPException(409, 'Scheduled marketing is disabled')
    try:
        blocked = operations.circuit(store())
        if blocked:
            return {'status': 'blocked', 'reason': blocked['reason'], 'run_id': blocked.get('run_id')}
        config = marketing.profile()
        marketing.delivery_config()
        if not os.getenv('LLM_MODEL'):
            raise ValueError('LLM_MODEL is not configured')
        slot = marketing.schedule_slot(config)
        if slot is None:
            return {'status': 'not_due'}
        # Reject a broken destination before reserving a daily slot or spending
        # on the model. A corrected Meta grant can then recover on the next poll.
        marketing.verify_delivery()
        brief = CampaignRequest(campaign_key=config['campaign_key'], brief=config['brief'], audience=config['audience'],
                                channels=['facebook'], brand_guidelines=config.get('brand_guidelines', ''),
                                source_material=config['business_facts']).model_dump()
        after, before = marketing.publication_window(config)
        run, created = store().schedule(config['campaign_key'] + ':' + slot, brief,
                                       publish_after=after.isoformat(), publish_before=before.isoformat())
        if created:
            store().event(run['id'], 'scheduled_run_created', slot=slot, campaign_key=config['campaign_key'],
                          publish_after=run['publish_after'], publish_before=run['publish_before'])
        retried = False
        if run['status'] == 'failed':
            try:
                run = store().retry_generation(run['id'], 'bounded-automatic-recovery', automatic=True)
                retried = True
            except ValueError:
                pass  # Preserve the failure and diagnostics when recovery is ineligible.
        return dict(campaign_state(run), created=created, retried=retried)
    except httpx.HTTPError as exc:
        diagnostic = error_details(exc)
        store().event('runtime', 'facebook_delivery_check_failed', status='failed',
                      operation='facebook.preflight', error=diagnostic)
        raise HTTPException(409, {'reason': 'Facebook Page validation failed before generation', 'error': diagnostic}) from None
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Marketing profile unavailable') from None


@app.post('/automation/publish', dependencies=[Depends(authorize)])
@otel.observed('publication.batch')
def automation_publish():
    results = []
    for candidate in store().recent():
        run = store().get(candidate['id'])
        if run['status'] == 'approved' and run.get('scheduled'):
            try:
                results.append(marketing.publish_one(store(), run['id']))
            except ValueError as exc:
                results.append({'run_id': run['id'], 'status': 'blocked', 'reason': str(exc)})
                if str(exc) == 'Publication is not due yet':
                    results[-1].update(status='not_due', publish_after=run.get('publish_after'), publish_before=run.get('publish_before'))
                elif run.get('publication_blocker') != str(exc):
                    store().update(run['id'], publication_blocker=str(exc))
                    store().event(run['id'], 'facebook_publication_blocked', status='blocked', reason=str(exc))
    db = store()
    runs = [db.get(candidate['id']) for candidate in db.recent()]
    states = [campaign_state(run) for run in runs if run.get('scheduled')]
    # Report today's unresolved campaigns even when there is nothing approved to send.
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(marketing.profile().get('timezone', 'America/Chicago'))).date().isoformat()
    states = [state for state in states if (state.get('publish_before') or '').startswith(today)]
    return {'publications': results, 'campaigns': states,
            'status': 'blocked' if any(s['status'] in PROBLEM_STATES for s in states) else
                      ('published' if any(p['status'] == 'published' for p in results) else 'idle')}


@app.post('/automation/metrics', dependencies=[Depends(authorize)])
@otel.observed('engagement.collect')
def automation_metrics():
    try:
        results = marketing.collect_metrics(store())
        failed = any(result.get('status') == 'failed' for result in results)
        partial = any(result.get('status') == 'partial' for result in results)
        return {'results': results, 'status': 'failed' if failed else ('partial' if partial else 'completed'),
                'reason': 'Facebook metrics collection failed; inspect facebook_metrics_failed events' if failed else
                          ('Some metrics unavailable; inspect missing_metrics and Meta permissions' if partial else None)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.get('/automation/status', dependencies=[Depends(authorize)])
def automation_status():
    return {'runs': [campaign_state(store().get(run['id'])) for run in store().recent()],
            'publications': store().social_recent()}


PROBLEM_STATES = {'failed', 'awaiting_review', 'publication_failed', 'publication_unknown', 'expired', 'blocked', 'unknown'}


def campaign_state(run):
    reason = run.get('publication_blocker') or run.get('error')
    policy = recovery.classify(run.get('error_details') or {})
    if run['status'] == 'failed' and policy['pause_generation']:
        reason = policy['reason']
    return dict(run_id=run['id'], id=run['id'], status=run['status'], campaign_key=run.get('campaign_key'),
                created_at=run['created_at'], attempt=run.get('attempts', 0),
                publish_after=run.get('publish_after'), publish_before=run.get('publish_before'),
                reason=reason, error=run.get('error_details'),
                failure_category=run.get('failure_category'),
                retryable=run.get('retryable', False), retry_after=run.get('retry_after'),
                generation_settings=run.get('generation_settings'))


@app.get('/automation/delivery-check', dependencies=[Depends(authorize)])
def delivery_check():
    try:
        return marketing.verify_delivery()
    except (ValueError, httpx.HTTPError) as exc:
        diagnostic = error_details(exc)
        store().event('runtime', 'facebook_delivery_check_failed', status='failed',
                      operation='facebook.preflight', error=diagnostic)
        raise HTTPException(409, {'reason': 'Facebook Page validation failed', 'error': diagnostic}) from None


@app.get('/automation/research-check', dependencies=[Depends(authorize)])
def research_check():
    """Verify that current source material is reachable without exposing article text."""
    try:
        sources, failures = marketing.source_context(marketing.profile())
        published = [item['published_at'] for item in sources if item.get('published_at')]
        domains = sorted({urlsplit(item['url']).hostname for item in sources if urlsplit(item['url']).hostname})
        return {'status': 'ready', 'item_count': len(sources), 'recent_item_count': len(published),
                'newest_published_at': max(published) if published else None,
                'source_domains': domains, 'feed_failures': failures}
    except (ValueError, OSError, httpx.HTTPError) as exc:
        diagnostic = error_details(exc)
        store().event('runtime', 'research_check_failed', status='failed',
                      operation='research.preflight', error=diagnostic)
        raise HTTPException(409, {'reason': 'Current-topic research validation failed',
                                  'error': diagnostic}) from None


class GenerationRetry(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)


@app.post('/runs/{run_id}/retry-generation', dependencies=[Depends(authorize)], status_code=202)
def retry_generation(run_id: str, payload: GenerationRetry):
    if os.getenv('MARKETING_AUTOMATION_ENABLED', 'false').lower() != 'true':
        raise HTTPException(409, 'Scheduled marketing is disabled')
    try:
        marketing.delivery_config()
        if not os.getenv('LLM_MODEL'):
            raise ValueError('LLM_MODEL is not configured')
        return campaign_state(store().retry_generation(run_id, payload.reviewer))
    except KeyError:
        raise HTTPException(404, 'Run not found') from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.get('/observability/status', dependencies=[Depends(authorize)])
def observability_status():
    return {**telemetry.status(store()), 'langsmith': langsmith_trace.status()}


@app.post('/observability/dead-letters/{event_id}/requeue', dependencies=[Depends(authorize)])
def requeue_telemetry(event_id: int):
    try:
        store().requeue_log(event_id)
    except KeyError:
        raise HTTPException(404, 'Quarantined event not found') from None
    store().event('runtime', 'telemetry_requeue_requested', operation='telemetry.requeue', remote_id=str(event_id))
    return {'status': 'queued', 'event_id': event_id}


@app.post('/runs/{run_id}/evaluations', dependencies=[Depends(authorize)])
def submit_evaluation(run_id: str, payload: evaluation.Evaluation):
    try:
        with otel.span('quality.evaluate', {'run.id': run_id}, linked=get_run(run_id).get('execution_trace')):
            return evaluation.record(store(), run_id, payload)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.get('/runs/{run_id}/replay-bundle', dependencies=[Depends(authorize)])
def download_replay(run_id: str):
    if os.getenv('REPLAY_EXPORT_ENABLED', 'false').lower() != 'true':
        raise HTTPException(403, 'Replay export is disabled by content access policy')
    get_run(run_id)
    bundle = evaluation.replay_bundle(store(), run_id)
    store().event(run_id, 'replay_bundle_exported', operation='replay.export')
    return JSONResponse(bundle, headers={'Content-Disposition': 'attachment; filename="replay.json"',
                                         'Cache-Control': 'no-store'})


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
        if db.get(record['run_id']).get('scheduled'):
            atlassian.sync_scheduled(db, record['run_id'])
        return result
    except KeyError:
        raise HTTPException(404, 'Publication not found') from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except httpx.HTTPError:
        raise HTTPException(502, 'Cannot verify post with Facebook') from None


PUBLIC_ARTICLE_STATES = {'publishing', 'published', 'publication_unknown', 'publication_failed'}


@otel.observed('artwork.generate')
def create_article_artwork(db, run_id, artifact):
    token = otel.RUN.set({'id': run_id, 'db': db})
    try:
        return _create_article_artwork(db, run_id, artifact)
    finally:
        otel.RUN.reset(token)


def _create_article_artwork(db, run_id, artifact):
    try:
        result = marketing.generate_article_artwork(DATA_DIR, run_id, artifact)
        if result['status'] == 'ready':
            db.event(run_id, 'article_artwork_generated', status='completed', operation='openai.image.generate',
                     image_model=result['model'], image_size=result['size'], image_quality=result['quality'],
                     artwork_url='/articles/' + run_id + '/artwork.webp')
        return result
    except Exception as exc:
        diagnostic = error_details(exc)
        db.event(run_id, 'article_artwork_failed', status='partial', operation='openai.image.generate',
                 error=diagnostic)
        logger.warning('run=%s article_artwork_failed %s', run_id, json.dumps(diagnostic))
        return {'status': 'failed', 'error_type': diagnostic['kind']}


def backfill_article_artwork(db):
    """Create one missing hero for the latest public article after a deployment."""
    try:
        if marketing.artwork_settings() is None:
            return
        for candidate in db.recent():
            run = db.get(candidate['id'])
            if (run['status'] in PUBLIC_ARTICLE_STATES and run.get('approval') and run.get('artifact')
                    and not run.get('article_artwork')):
                artwork = create_article_artwork(db, run['id'], run['artifact'])
                db.update(run['id'], article_artwork=artwork)
                return
    except Exception as exc:
        diagnostic = error_details(exc)
        db.event('runtime', 'article_artwork_backfill_failed', status='partial',
                 operation='openai.image.generate', error=diagnostic)
        logger.warning('article_artwork_backfill_failed %s', json.dumps(diagnostic))


def public_article(run_id):
    run = get_run(run_id)
    if run['status'] not in PUBLIC_ARTICLE_STATES or not run.get('approval'):
        raise HTTPException(404, 'Article not published')
    articles = (run.get('artifact') or {}).get('articles', [])
    if not articles:
        raise HTTPException(404, 'Article not found')
    return run


ARTICLE_HEADERS = {
    'Cache-Control': 'public, max-age=300',
    'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'X-Content-Type-Options': 'nosniff',
}


@app.get('/', include_in_schema=False)
def home():
    return RedirectResponse('/insights', status_code=307)


@app.get('/insights', response_class=HTMLResponse)
def insights():
    db = store()
    items = []
    for candidate in db.recent():
        run = db.get(candidate['id'])
        if run['status'] in PUBLIC_ARTICLE_STATES and run.get('approval') and (run.get('artifact') or {}).get('articles'):
            items.append((run['id'], run, bool(marketing.artwork_path(DATA_DIR, run.get('article_artwork')))))
    return HTMLResponse(article_view.render_index(items), headers=ARTICLE_HEADERS)


@app.get('/articles/{run_id}', response_class=HTMLResponse)
def article(run_id: str):
    run = public_article(run_id)
    artwork = marketing.artwork_path(DATA_DIR, run.get('article_artwork'))
    page = article_view.render(run, run_id, os.getenv('PUBLIC_API_BASE_URL', ''), artwork=bool(artwork))
    return HTMLResponse(page, headers=ARTICLE_HEADERS)


@app.get('/articles/{run_id}/artwork.webp', response_class=FileResponse)
def article_artwork(run_id: str):
    run = public_article(run_id)
    path = marketing.artwork_path(DATA_DIR, run.get('article_artwork'))
    if not path:
        raise HTTPException(404, 'Article artwork not found')
    return FileResponse(path, media_type='image/webp', headers={
        'Cache-Control': 'public, max-age=31536000, immutable',
        'X-Content-Type-Options': 'nosniff',
    })


class OperationOutcome(BaseModel):
    run_id: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=2000)
    publish_after: str | None = Field(default=None, max_length=100)
    publish_before: str | None = Field(default=None, max_length=100)
    remote_id: str | None = Field(default=None, max_length=100)


class AutomationResult(OperationOutcome):
    campaigns: list[OperationOutcome] = Field(default_factory=list, max_length=100)
    publications: list[OperationOutcome] = Field(default_factory=list, max_length=100)
    results: list[OperationOutcome] = Field(default_factory=list, max_length=100)


class WorkflowEvent(BaseModel):
    execution_id: str = Field(max_length=100)
    workflow_name: str = Field(max_length=200)
    status: str = Field(pattern=r'^(failed|started|completed)$')
    operation: str | None = Field(default=None, max_length=200)
    node: str | None = Field(default=None, max_length=200)
    execution_url: str | None = Field(default=None, max_length=500)
    error_message: str | None = Field(default=None, max_length=2000)
    result: AutomationResult | None = None


@app.post('/automation/events', dependencies=[Depends(authorize)])
def workflow_event(payload: WorkflowEvent):
    db = store()
    outcomes = []
    if payload.result:
        outcomes = [payload.result, *payload.result.campaigns, *payload.result.publications, *payload.result.results]
    failed = payload.status == 'failed' or any(item.status in PROBLEM_STATES for item in outcomes)
    status = 'failed' if failed else payload.status
    metadata = dict(execution_id=payload.execution_id, workflow_name=payload.workflow_name,
                    operation=payload.operation, node=payload.node, execution_url=payload.execution_url)
    reason = redact(payload.error_message) if payload.error_message else None
    if not reason:
        reason = next((item.reason for item in outcomes if item.status in PROBLEM_STATES and item.reason), None)
        reason = reason or next(('Campaign outcome: ' + str(item.status) for item in outcomes if item.status in PROBLEM_STATES), None)
    run_ids = list(dict.fromkeys(item.run_id for item in outcomes if item.run_id))
    if not run_ids and payload.error_message and 'runs=' in payload.error_message:
        run_ids = re.findall(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', payload.error_message.split('runs=', 1)[1])[:100]
    for run_id in run_ids:
        try:
            state = campaign_state(db.get(run_id))
        except KeyError:
            continue
        state.pop('run_id')
        state.pop('id')
        db.event(run_id, 'n8n_campaign_observed', **state, **metadata)
    db.event('n8n:' + payload.execution_id, 'n8n_execution_' + status,
             status=status, reason=reason, run_ids=run_ids,
             outcome=payload.result.status if payload.result else status,
             outcomes=[item.model_dump(exclude_none=True, exclude={'campaigns', 'publications', 'results'}) for item in outcomes],
             **metadata)
    if failed:
        if run_ids:
            for run_id in run_ids:
                notifications.incident(db, 'campaign:' + run_id, 'Daily campaign requires attention', reason or 'Workflow failed', run_id)
        else:
            notifications.incident(db, 'workflow:' + payload.workflow_name + ':' + (payload.node or payload.operation or 'unknown'),
                                   'Workflow operation failed: ' + payload.workflow_name, reason or 'Inspect n8n execution ' + payload.execution_id)
    elif payload.status == 'completed':
        notifications.resolve(db, 'workflow:' + payload.workflow_name + ':' + (payload.node or payload.operation or 'unknown'),
                              'Workflow operation completed successfully again.')
    return {'recorded': True, 'failed': failed, 'reason': reason, 'run_ids': run_ids,
            'notifications_managed': notifications.enabled()}


class RecoveryResume(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    run_id: str | None = Field(default=None, max_length=100)


@app.get('/automation/operations/status', dependencies=[Depends(authorize)])
def operational_status():
    return operations.status(store())


@app.post('/automation/recovery/resume', dependencies=[Depends(authorize)])
def resume_generation(payload: RecoveryResume):
    try:
        return operations.resume(store(), payload.reviewer, payload.run_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else 'Run not found') from None


@app.post('/automation/notifications/{delivery_id}/retry', dependencies=[Depends(authorize)])
def retry_notification(delivery_id: str, payload: RecoveryResume):
    try:
        return notifications.retry(store(), delivery_id, payload.reviewer)
    except KeyError:
        raise HTTPException(404, 'Notification delivery not found') from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
