"""ServiceNow Table API. https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI"""

from typing import Any, Literal

import httpx

from relay_agents.connectors.ports import TicketDraft, TicketWriteError
from relay_agents.contracts import TicketRef
from relay_agents.tenants import ServiceNowConfig


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
