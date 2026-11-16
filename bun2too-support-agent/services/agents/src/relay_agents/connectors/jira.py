"""Jira Cloud REST v3. https://developer.atlassian.com/cloud/jira/platform/rest/v3/"""

from typing import Any, Literal

import httpx

from relay_agents.connectors.ports import TicketDraft, TicketWriteError
from relay_agents.contracts import TicketRef
from relay_agents.tenants import JiraConfig


def _adf(text: str) -> dict[str, Any]:
    paragraphs = [p for p in text.split("\n\n") if p.strip()] or [" "]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs
        ],
    }


class JiraTicketPort:
    system: Literal["jira"] = "jira"

    def __init__(self, client: httpx.AsyncClient, base_url: str, config: JiraConfig) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._config = config

    async def _find(self, correlation_key: str) -> str | None:
        response = await self._send(
            "GET",
            "/rest/api/3/search/jql",
            params={"jql": f'labels = "{correlation_key}"', "fields": "key", "maxResults": "1"},
        )
        issues = response.json().get("issues", [])
        return str(issues[0]["key"]) if issues else None

    async def ensure_ticket(self, draft: TicketDraft) -> TicketRef:
        key = await self._find(draft.correlation_key)
        if key is None:
            fields: dict[str, Any] = {
                "project": {"key": self._config.project},
                "issuetype": {"name": self._config.issue_type},
                "summary": draft.title[:250],
                "description": _adf(draft.description),
                "labels": [draft.correlation_key, "relay", *draft.labels],
                "priority": {"name": self._config.priority_map[draft.severity]},
            }
            created = await self._send("POST", "/rest/api/3/issue", json={"fields": fields})
            key = str(created.json()["key"])
        return TicketRef(system="jira", key=key, url=f"{self._base}/browse/{key}")

    async def add_note(self, correlation_key: str, text: str) -> None:
        key = await self._require(correlation_key)
        await self._send("POST", f"/rest/api/3/issue/{key}/comment", json={"body": _adf(text)})

    async def resolve(self, correlation_key: str, text: str) -> None:
        key = await self._require(correlation_key)
        await self._send("POST", f"/rest/api/3/issue/{key}/comment", json={"body": _adf(text)})
        if self._config.resolve_transition_id:
            await self._send(
                "POST",
                f"/rest/api/3/issue/{key}/transitions",
                json={"transition": {"id": self._config.resolve_transition_id}},
            )

    async def _require(self, correlation_key: str) -> str:
        key = await self._find(correlation_key)
        if key is None:
            raise TicketWriteError(f"no Jira issue labelled {correlation_key}")
        return key

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, f"{self._base}{path}", **kwargs)
        except httpx.HTTPError as error:
            raise TicketWriteError(f"jira {method} {path}: {error}") from error
        if response.status_code >= 400:
            raise TicketWriteError(f"jira {method} {path}: HTTP {response.status_code}")
        return response
