import asyncio
import json

import httpx
import pytest

from relay_agents.connectors.jira import JiraTicketPort
from relay_agents.connectors.ports import TicketDraft, TicketWriteError
from relay_agents.connectors.servicenow import ClientCredentials, ServiceNowTicketPort
from relay_agents.tenants import JiraConfig, ServiceNowConfig

DRAFT = TicketDraft(
    correlation_key="relay-acme-case_1",
    title="[sev3] Login fails",
    description="d",
    severity="sev3",
)
JIRA = JiraConfig(project="SUP", base_url_env="X", email_env="Y", token_env="Z")
SNOW = ServiceNowConfig(instance_url_env="X", client_id_env="Y", client_secret_env="Z")
INSTANCE = "https://dev.service-now.com"
SECRET = "client-secret-value"


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
    """The Table API behind an OAuth token endpoint that issues tok-1, tok-2, ..."""

    def __init__(self, token_status: int = 200) -> None:
        self.rows: list[dict[str, str]] = []
        self.patches: list[dict[str, str]] = []
        self.token_status = token_status
        self.tokens: list[dict[str, str]] = []
        self.valid: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            form = dict(httpx.QueryParams(request.content.decode()))
            self.tokens.append(form)
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "access_denied"})
            token = f"tok-{len(self.tokens)}"
            self.valid.add(token)
            return httpx.Response(200, json={"access_token": token, "expires_in": 1799})
        if request.headers.get("Authorization", "").removeprefix("Bearer ") not in self.valid:
            return httpx.Response(401, json={"error": {"message": "User Not Authenticated"}})
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


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _snow(fake: FakeServiceNow, clock: Clock | None = None) -> ServiceNowTicketPort:
    auth = ClientCredentials(INSTANCE, "client-id", SECRET, clock=clock or Clock())
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake), auth=auth)
    return ServiceNowTicketPort(client, INSTANCE, SNOW)


async def test_servicenow_ensure_then_resolve_uses_correlation_id() -> None:
    fake = FakeServiceNow()
    port = _snow(fake)

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


async def test_servicenow_gets_one_client_credentials_token_and_reuses_it() -> None:
    fake = FakeServiceNow()
    port = _snow(fake)

    await port.ensure_ticket(DRAFT)
    await port.add_note(DRAFT.correlation_key, "note")

    assert fake.tokens == [
        {"grant_type": "client_credentials", "client_id": "client-id", "client_secret": SECRET}
    ]


async def test_servicenow_fetches_a_new_token_before_the_old_one_expires() -> None:
    fake = FakeServiceNow()
    clock = Clock()
    port = _snow(fake, clock)

    await port.ensure_ticket(DRAFT)
    clock.now = 1799 - ClientCredentials.EARLY
    await port.ensure_ticket(DRAFT)

    assert len(fake.tokens) == 2


async def test_servicenow_retries_once_with_a_new_token_after_a_401() -> None:
    fake = FakeServiceNow()
    port = _snow(fake)
    await port.ensure_ticket(DRAFT)
    fake.valid.clear()  # the instance revoked the token early

    await port.add_note(DRAFT.correlation_key, "note")

    assert len(fake.tokens) == 2
    assert fake.patches == [{"work_notes": "note"}]


async def test_a_refused_token_is_a_ticket_write_error_without_the_secret() -> None:
    port = _snow(FakeServiceNow(token_status=401))
    with pytest.raises(TicketWriteError, match="token request: HTTP 401") as raised:
        await port.ensure_ticket(DRAFT)
    assert SECRET not in str(raised.value)


class LoopbackServiceNow:
    """A real HTTP server on loopback whose token endpoint can hang, so client timeouts apply."""

    def __init__(self, tokens_before_hang: int, table_oks: int) -> None:
        self.tokens_left = tokens_before_hang
        self.table_oks = table_oks
        self.server: asyncio.Server | None = None

    async def __aenter__(self) -> str:
        self.server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def __aexit__(self, *_: object) -> None:
        assert self.server is not None
        self.server.close()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode()
        length = next(
            (
                int(h.split(":")[1])
                for h in head.split("\r\n")
                if h.lower().startswith("content-length")
            ),
            0,
        )
        await reader.readexactly(length)
        if " /oauth_token.do " in head.split("\r\n")[0]:
            if self.tokens_left == 0:
                await asyncio.sleep(3600)
            self.tokens_left -= 1
            status, body = 200, {"access_token": "tok", "expires_in": 1799}
        elif self.table_oks > 0:
            self.table_oks -= 1
            status, body = 200, {"result": [{"sys_id": "s1", "number": "INC1"}]}
        else:
            status, body = 401, {"error": {"message": "User Not Authenticated"}}
        data = json.dumps(body).encode()
        writer.write(
            f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode()
            + data
        )
        await writer.drain()
        writer.close()


def _loopback_snow(url: str) -> ServiceNowTicketPort:
    auth = ClientCredentials(url, "client-id", SECRET)
    return ServiceNowTicketPort(httpx.AsyncClient(auth=auth, timeout=0.05), url, SNOW)


async def test_a_hung_token_request_times_out_with_the_clients_timeout() -> None:
    async with LoopbackServiceNow(tokens_before_hang=0, table_oks=0) as url:
        port = _loopback_snow(url)
        with pytest.raises(TicketWriteError) as raised:
            await asyncio.wait_for(port.ensure_ticket(DRAFT), timeout=2)
        assert isinstance(raised.value.__cause__, httpx.TimeoutException)


async def test_a_hung_token_refresh_after_a_401_times_out_too() -> None:
    async with LoopbackServiceNow(tokens_before_hang=1, table_oks=1) as url:
        port = _loopback_snow(url)
        await port.ensure_ticket(DRAFT)  # token cached; the lookup finds INC1
        with pytest.raises(TicketWriteError) as raised:
            await asyncio.wait_for(port.ensure_ticket(DRAFT), timeout=2)
        assert isinstance(raised.value.__cause__, httpx.TimeoutException)
