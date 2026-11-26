"""ServiceNow Table API. https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI"""

import time
from collections.abc import Callable, Generator
from typing import Any, Literal

import httpx

from relay_agents.connectors.ports import TicketDraft, TicketWriteError
from relay_agents.contracts import TicketRef
from relay_agents.tenants import ServiceNowConfig


class ClientCredentials(httpx.Auth):
    """OAuth client-credentials grant: one bearer token, reused until shortly before it expires.

    A 401 on a call fetches a new token and retries that call once.
    """

    requires_response_body = True
    EARLY = 60.0

    def __init__(
        self,
        instance_url: str,
        client_id: str,
        client_secret: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._token_url = f"{instance_url.rstrip('/')}/oauth_token.do"
        self._form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        self._clock = clock
        self._token: str | None = None
        self._expires = 0.0

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        fresh = self._token is None or self._clock() >= self._expires
        if fresh:
            self._store((yield self._token_request(request)))
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request
        if response.status_code == 401 and not fresh:
            self._store((yield self._token_request(request)))
            request.headers["Authorization"] = f"Bearer {self._token}"
            yield request

    def _token_request(self, request: httpx.Request) -> httpx.Request:
        # A request the flow builds itself gets no client defaults; carry the caller's timeout.
        timeout = (
            {"timeout": request.extensions["timeout"]} if "timeout" in request.extensions else {}
        )
        return httpx.Request("POST", self._token_url, data=self._form, extensions=timeout)

    def _store(self, response: httpx.Response) -> None:
        token = response.json().get("access_token") if response.status_code == 200 else None
        if not token:
            raise httpx.HTTPStatusError(
                f"ServiceNow token request: HTTP {response.status_code}",
                request=response.request,
                response=response,
            )
        self._token = str(token)
        self._expires = self._clock() + float(response.json().get("expires_in", 0)) - self.EARLY


class ServiceNowTicketPort:
    system: Literal["servicenow"] = "servicenow"

    def __init__(
        self, client: httpx.AsyncClient, instance_url: str, config: ServiceNowConfig
    ) -> None:
        self._client = client
        self._base = instance_url.rstrip("/")
        self._config = config
        self._path = f"/api/now/table/{config.table}"

    async def _find(self, correlation_key: str) -> dict[str, Any] | None:
        response = await self._send(
            "GET",
            self._path,
            params={
                "sysparm_query": f"correlation_id={correlation_key}",
                "sysparm_fields": "sys_id,number",
                "sysparm_limit": "1",
            },
        )
        rows = response.json().get("result", [])
        return dict(rows[0]) if rows else None

    def _ref(self, row: dict[str, Any]) -> TicketRef:
        url = f"{self._base}/nav_to.do?uri={self._config.table}.do?sys_id={row['sys_id']}"
        return TicketRef(system="servicenow", key=str(row["number"]), url=url)

    async def ensure_ticket(self, draft: TicketDraft) -> TicketRef:
        row = await self._find(draft.correlation_key)
        if row is None:
            body: dict[str, str] = {
                "short_description": draft.title[:160],
                "description": draft.description,
                "correlation_id": draft.correlation_key,
                "correlation_display": "Relay",
                "urgency": self._config.urgency_map[draft.severity],
            }
            if self._config.assignment_group:
                body["assignment_group"] = self._config.assignment_group
            created = await self._send("POST", self._path, json=body)
            row = dict(created.json()["result"])
        return self._ref(row)

    async def add_note(self, correlation_key: str, text: str) -> None:
        sys_id = await self._require(correlation_key)
        await self._send("PATCH", f"{self._path}/{sys_id}", json={"work_notes": text})

    async def resolve(self, correlation_key: str, text: str) -> None:
        sys_id = await self._require(correlation_key)
        body = {**self._config.resolve_fields, "close_notes": text}
        await self._send("PATCH", f"{self._path}/{sys_id}", json=body)

    async def _require(self, correlation_key: str) -> str:
        row = await self._find(correlation_key)
        if row is None:
            raise TicketWriteError(f"no ServiceNow record with correlation_id {correlation_key}")
        return str(row["sys_id"])

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(
                method, f"{self._base}{path}", headers={"Accept": "application/json"}, **kwargs
            )
        except httpx.HTTPError as error:
            raise TicketWriteError(f"servicenow {method} {path}: {error}") from error
        if response.status_code >= 400:
            raise TicketWriteError(f"servicenow {method} {path}: HTTP {response.status_code}")
        return response
