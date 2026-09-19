import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient

from crewai_agents.app import main
from crewai_agents.app.models import MarketingArtifact
from crewai_agents.app.store import Store


def artifact():
    return MarketingArtifact(
        campaign_plan="Plan", requirements="Requirements", creative_brief="Design brief",
        engineering_plan="Tickets", delivery_plan="Schedule", measurement_plan="Metrics",
        posts=[{"channel": "facebook", "text": "Reviewed bun2too post"}], blockers=[])


class APITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {
            "MARKETING_API_KEY": "test-key", "LLM_MODEL": "test-model",
            "PUBLISHING_ENABLED": "false", "N8N_WEBHOOK_URL": "https://n8n.example/webhook/test",
            "N8N_WEBHOOK_TOKEN": "webhook-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        data = patch.object(main, "DATA_DIR", Path(self.directory.name))
        data.start()
        self.addCleanup(data.stop)
        self.client = TestClient(main.app)
        self.client.headers["Authorization"] = "Bearer test-key"

    def draft(self):
        run = main.store().create({"channels": ["facebook"]})
        main.store().update(run["id"], status="awaiting_review", artifact=artifact().model_dump())
        return run["id"]

    def test_auth_fails_closed(self):
        self.assertEqual(TestClient(main.app).get("/runs").status_code, 401)
        with patch.dict(os.environ, {"MARKETING_API_KEY": ""}):
            self.assertEqual(self.client.get("/runs").status_code, 503)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_campaign_records_outputs_and_persists(self):
        def build(brief, callback, **kwargs):
            def kickoff():
                callback("product_owner", "Objectives and assumptions")
                return SimpleNamespace(pydantic=artifact())
            return SimpleNamespace(kickoff=kickoff)
        with patch.object(main, "build_crew", side_effect=build):
            response = self.client.post("/campaigns", json={"brief": "Launch campaign"})
        self.assertEqual(response.status_code, 202)
        run = self.client.get(response.json()["review_url"]).json()
        self.assertEqual(run["status"], "awaiting_review")
        self.assertEqual(run["tasks"][0]["agent"], "product_owner")
        self.assertEqual(Store(main.DATA_DIR / "runs.sqlite3").get(run["id"]), run)

    def test_legacy_post_response(self):
        crew = SimpleNamespace(kickoff=lambda: SimpleNamespace(pydantic=artifact()))
        with patch.object(main, "build_crew", return_value=crew):
            response = self.client.post("/generate-post", json={"article_text": "Our launch"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["generated_post"], "Reviewed bun2too post")

    def test_failure_does_not_leak_provider_message(self):
        with patch.object(main, "build_crew", side_effect=RuntimeError("secret-key")):
            response = self.client.post("/campaigns", json={"brief": "Launch campaign"})
        run = self.client.get(response.json()["review_url"])
        self.assertEqual(run.json()["status"], "failed")
        self.assertNotIn("secret-key", run.text)

    def test_approval_and_dispatch_gates(self):
        run_id = self.draft()
        endpoint = f"/runs/{run_id}/dispatch"
        with patch.object(main.httpx, "post") as send:
            self.assertEqual(self.client.post(endpoint).status_code, 403)
            with patch.dict(os.environ, {"PUBLISHING_ENABLED": "true"}):
                self.assertEqual(self.client.post(endpoint).status_code, 409)
            send.assert_not_called()
        edited = artifact().model_dump()
        edited["blockers"] = ["Verify claim"]
        response = self.client.post(f"/runs/{run_id}/approve", json={"reviewer": "owner", "artifact": edited})
        self.assertEqual(response.status_code, 409)
        edited["blockers"] = []
        edited["posts"][0]["text"] = "Human edited final copy"
        approved = self.client.post(f"/runs/{run_id}/approve", json={"reviewer": "owner", "artifact": edited})
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(len(approved.json()["approval"]["sha256"]), 64)
        with patch.dict(os.environ, {"PUBLISHING_ENABLED": "true"}), patch.object(main.httpx, "post", return_value=Mock()) as send:
            self.assertEqual(self.client.post(endpoint).json()["status"], "submitted")
            self.assertEqual(send.call_args.kwargs["json"]["artifact"], edited)
            self.assertEqual(send.call_args.kwargs["headers"]["Idempotency-Key"], run_id)
            self.assertEqual(self.client.post(endpoint).status_code, 409)
            send.assert_called_once()

    def test_timeout_blocks_retry(self):
        run_id = self.draft()
        self.client.post(f"/runs/{run_id}/approve", json={"reviewer": "owner"})
        with patch.dict(os.environ, {"PUBLISHING_ENABLED": "true"}), patch.object(main.httpx, "post", side_effect=httpx.ReadTimeout("secret")) as send:
            self.assertEqual(self.client.post(f"/runs/{run_id}/dispatch").status_code, 502)
            self.assertEqual(self.client.get(f"/runs/{run_id}").json()["status"], "dispatch_unknown")
            self.assertEqual(self.client.post(f"/runs/{run_id}/dispatch").status_code, 409)
            send.assert_called_once()

    def test_atomic_dispatch_claim(self):
        run_id = self.draft()
        main.store().update(run_id, status="approved")
        def claim(_):
            try:
                main.store().update(run_id, expected={"approved"}, status="dispatching")
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(claim, range(2))), 1)

    def test_unknown_run_and_invalid_input(self):
        self.assertEqual(self.client.get("/runs/missing").status_code, 404)
        self.assertEqual(self.client.post("/campaigns", json={"brief": ""}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
