from fastapi.testclient import TestClient

from relay_agents.api import create_app
from relay_agents.service import CaseService


def test_intake_runs_in_background_and_case_is_readable(service: CaseService) -> None:
    client = TestClient(create_app(service, offline=True))
    command = {
        "tenant": "bun2too",
        "idempotencyKey": "api-1",
        "intake": {"channel": "web_widget", "message": "How do I send a private inquiry?"},
    }

    created = client.post("/runs/intake", json=command)
    assert created.status_code == 202
    case_id = created.json()["caseId"]

    case = client.get(f"/tenants/bun2too/cases/{case_id}").json()
    assert case["status"] == "resolved"
    assert case["pendingQuestion"] is None
    assert client.post("/runs/intake", json=command).status_code == 200


def test_cases_are_scoped_to_their_tenant(service: CaseService) -> None:
    client = TestClient(create_app(service, offline=True))
    created = client.post(
        "/runs/intake",
        json={
            "tenant": "bun2too",
            "idempotencyKey": "api-2",
            "intake": {"channel": "email", "message": "hi"},
        },
    )
    case_id = created.json()["caseId"]
    assert client.get(f"/tenants/other/cases/{case_id}").status_code == 404


def test_unknown_tenant_is_rejected(service: CaseService) -> None:
    client = TestClient(create_app(service, offline=True))
    response = client.post(
        "/runs/intake",
        json={
            "tenant": "nobody",
            "idempotencyKey": "x",
            "intake": {"channel": "email", "message": "hi"},
        },
    )
    assert response.status_code == 404
