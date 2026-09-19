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

from .crews import build_crew
from .models import ApprovalRequest, CampaignRequest, GenerationRequest, MarketingArtifact
from .store import Store, now

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
    try:
        def record_task(role, output):
            db.update(run_id, task=dict(agent=role, completed_at=now(), output=output))
            logger.info("run=%s completed_agent=%s", run_id, role)

        crew = build_crew(run["brief"], record_task, social_only=social_only)
        result = crew.kickoff()
        artifact = (MarketingArtifact.model_validate(result.pydantic) if result.pydantic
                    else MarketingArtifact.model_validate_json(result.raw))
        allowed = {channel.lower() for channel in run["brief"]["channels"]}
        if any(post.channel.lower() not in allowed for post in artifact.posts):
            raise ValueError("Artifact contains an unrequested channel")
        db.update(run_id, status="awaiting_review", artifact=artifact.model_dump())
    except Exception as exc:
        # Provider errors can contain credentials or private prompts; do not expose them.
        logger.error("run=%s generation_failed type=%s", run_id, type(exc).__name__)
        db.update(run_id, status="failed", error="Generation failed (" + type(exc).__name__ + ")")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/campaigns", status_code=202, dependencies=[Depends(authorize)])
def create_campaign(payload: CampaignRequest, background: BackgroundTasks):
    if not os.getenv("LLM_MODEL"):
        raise HTTPException(503, "LLM_MODEL is not configured")
    run = store().create(payload.model_dump())
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
    return change_run(run_id, expected={"awaiting_review"}, status="approved",
                      artifact=artifact.model_dump(),
                      approval=dict(reviewer=payload.reviewer, approved_at=now(), sha256=digest))


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
