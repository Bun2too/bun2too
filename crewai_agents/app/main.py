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
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .crews import build_crew
from .models import ApprovalRequest, CampaignRequest, GenerationRequest, MarketingArtifact, LessonRequest
from .store import Store, now
from .observability import redact, workflow_span
from . import atlassian

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parents[1] / ".data")))
os.environ.setdefault("CREWAI_STORAGE_DIR", str((DATA_DIR / "crewai").resolve()))
logger = logging.getLogger(__name__)
app = FastAPI(title="bun2too Marketing Department API")
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
    run = db.update(run_id, expected={"queued"}, status="running")
    db.event(run_id, "run_started", operation="Crew.kickoff", model=os.getenv("LLM_MODEL"))
    try:
        def record_task(role, output, structured=None):
            task_id = run_id + ":" + role
            db.update(run_id, task=redact(dict(task_id=task_id, agent=role, completed_at=now(),
                                             output=output, structured=structured)))
            db.event(run_id, "task_completed", agent=role, task_id=task_id)
            logger.info("run=%s completed_agent=%s", run_id, role)

        brief = dict(run["brief"])
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
        if brief.get("campaign_key"):
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
