import json

import httpx
import pytest

from relay_agents.connectors.jira import JiraTicketPort
from relay_agents.connectors.ports import TicketDraft, TicketWriteError
from relay_agents.connectors.servicenow import ServiceNowTicketPort
from relay_agents.tenants import JiraConfig, ServiceNowConfig

DRAFT = TicketDraft(
    correlation_key="relay-acme-case_1",
    title="[sev3] Login fails",
    description="d",
    severity="sev3",
)
JIRA = JiraConfig(project="SUP", base_url_env="X", email_env="Y", token_env="Z")
SNOW = ServiceNowConfig(instance_url_env="X", user_env="Y", password_env="Z")


class FakeJira:
    def __init__(self) -> None:
        self.issues: dict[str, list[str]] = {}
        self.creates = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/search/jql":
            label = request.url.params["jql"].split('"')[1]
            hits = [{"key": k} for k, labels in self.issues.items() if label in labels]
            return httpx.Response(200, json={"issues": hits[:1]})
        if request.url.path == "/rest/api/3/issue" and request.method == "POST":
            self.creates += 1
            key = f"SUP-{self.creates}"
            self.issues[key] = json.loads(request.content)["fields"]["labels"]
            return httpx.Response(201, json={"id": "1", "key": key})
        return httpx.Response(201, json={})


async def test_jira_ensure_ticket_is_idempotent() -> None:
    fake = FakeJira()
    port = JiraTicketPort(
        httpx.AsyncClient(transport=httpx.MockTransport(fake)), "https://x.atlassian.net", JIRA
    )

    first = await port.ensure_ticket(DRAFT)
    second = await port.ensure_ticket(DRAFT)

    assert first == second
    assert first.url == "https://x.atlassian.net/browse/SUP-1"
    assert fake.creates == 1


class FakeServiceNow:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []
        self.patches: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            wanted = request.url.params["sysparm_query"].removeprefix("correlation_id=")
            return httpx.Response(
                200, json={"result": [r for r in self.rows if r["correlation_id"] == wanted]}
            )
        if request.method == "POST":
            body = json.loads(request.content)
            row = {"sys_id": f"s{len(self.rows)}", "number": f"INC00{len(self.rows)}", **body}
            self.rows.append(row)
            return httpx.Response(201, json={"result": row})
        self.patches.append(json.loads(request.content))
        return httpx.Response(200, json={"result": {}})


async def test_servicenow_ensure_then_resolve_uses_correlation_id() -> None:
    fake = FakeServiceNow()
    port = ServiceNowTicketPort(
        httpx.AsyncClient(transport=httpx.MockTransport(fake)), "https://dev.service-now.com", SNOW
    )

    ref = await port.ensure_ticket(DRAFT)
    again = await port.ensure_ticket(DRAFT)
    await port.resolve(DRAFT.correlation_key, "fixed")

    assert ref == again
    assert len(fake.rows) == 1
    assert fake.rows[0]["correlation_id"] == "relay-acme-case_1"
    assert fake.patches == [
        {"state": "6", "close_code": "Solution provided", "close_notes": "fixed"}
    ]


async def test_server_errors_surface_as_ticket_write_errors() -> None:
    failing = httpx.MockTransport(lambda _: httpx.Response(503))
    port = JiraTicketPort(httpx.AsyncClient(transport=failing), "https://x.atlassian.net", JIRA)
    with pytest.raises(TicketWriteError):
        await port.ensure_ticket(DRAFT)
