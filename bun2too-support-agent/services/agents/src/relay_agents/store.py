import asyncio
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

from relay_agents import case_machine
from relay_agents.contracts import Case, CaseEvent, CaseStatus, Channel


class CaseNotFound(Exception):
    pass


class CaseStore(Protocol):
    async def open(
        self, *, tenant: str, idempotency_key: str, channel: Channel, message: str, trace_id: str
    ) -> tuple[Case, bool]: ...

    async def get(self, tenant: str, case_id: str) -> Case | None: ...

    async def events(self, tenant: str, case_id: str, after: int = -1) -> list[CaseEvent]: ...

    async def messages(self, case_id: str) -> list[str]: ...

    async def add_message(self, case_id: str, text: str) -> None: ...

    async def move(
        self,
        case_id: str,
        target: CaseStatus,
        *,
        actor: str,
        reason: str,
        data: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> Case: ...

    async def note(
        self,
        case_id: str,
        *,
        actor: str,
        reason: str,
        data: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> Case: ...


class InMemoryCaseStore:
    def __init__(self) -> None:
        self._cases: dict[str, Case] = {}
        self._events: dict[str, list[CaseEvent]] = {}
        self._messages: dict[str, list[str]] = {}
        self._keys: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    async def open(
        self, *, tenant: str, idempotency_key: str, channel: Channel, message: str, trace_id: str
    ) -> tuple[Case, bool]:
        async with self._lock:
            existing = self._keys.get((tenant, idempotency_key))
            if existing:
                return self._cases[existing], False
            at = case_machine.now()
            case = Case(
                id=f"case_{uuid.uuid4().hex[:20]}",
                tenant=tenant,
                status="received",
                channel=channel,
                created_at=at,
                updated_at=at,
                trace_id=trace_id,
                classification=None,
                tickets=[],
                resolution=None,
                pending_question=None,
            )
            event = CaseEvent(
                seq=0,
                case_id=case.id,
                at=at,
                status="received",
                actor="intake",
                reason="intake accepted",
                data={"channel": channel},
            )
            self._cases[case.id] = case
            self._events[case.id] = [event]
            self._messages[case.id] = [message]
            self._keys[(tenant, idempotency_key)] = case.id
            return case, True

    async def get(self, tenant: str, case_id: str) -> Case | None:
        case = self._cases.get(case_id)
        return case if case and case.tenant == tenant else None

    async def events(self, tenant: str, case_id: str, after: int = -1) -> list[CaseEvent]:
        if not await self.get(tenant, case_id):
            return []
        return [e for e in self._events[case_id] if e.seq > after]

    async def messages(self, case_id: str) -> list[str]:
        return list(self._messages.get(case_id, []))

    async def add_message(self, case_id: str, text: str) -> None:
        async with self._lock:
            self._require(case_id)
            self._messages[case_id].append(text)

    async def move(
        self,
        case_id: str,
        target: CaseStatus,
        *,
        actor: str,
        reason: str,
        data: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> Case:
        async with self._lock:
            case = self._require(case_id)
            updated, event = case_machine.transition(
                case,
                target,
                seq=len(self._events[case_id]),
                actor=actor,
                reason=reason,
                data=data,
                **changes,
            )
            return self._commit(updated, event)

    async def note(
        self,
        case_id: str,
        *,
        actor: str,
        reason: str,
        data: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> Case:
        async with self._lock:
            case = self._require(case_id)
            updated, event = case_machine.note(
                case,
                seq=len(self._events[case_id]),
                actor=actor,
                reason=reason,
                data=data,
                **changes,
            )
            return self._commit(updated, event)

    def _require(self, case_id: str) -> Case:
        case = self._cases.get(case_id)
        if case is None:
            raise CaseNotFound(case_id)
        return case

    def _commit(self, case: Case, event: CaseEvent) -> Case:
        self._cases[case.id] = case
        self._events[case.id].append(event)
        return case
