from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from relay_agents.contracts import Case, CaseEvent, CaseStatus

TRANSITIONS: Mapping[CaseStatus, frozenset[CaseStatus]] = {
    "received": frozenset({"triaged", "rejected"}),
    "triaged": frozenset({"ticketed", "rejected"}),
    "ticketed": frozenset({"in_progress", "escalated"}),
    "in_progress": frozenset({"awaiting_customer", "resolved", "escalated"}),
    "awaiting_customer": frozenset({"in_progress", "escalated"}),
    "escalated": frozenset({"resolved"}),
    "resolved": frozenset({"in_progress"}),
    "rejected": frozenset(),
}


class IllegalTransition(Exception):
    def __init__(self, current: CaseStatus, target: CaseStatus) -> None:
        super().__init__(f"case cannot move from {current} to {target}")
        self.current = current
        self.target = target


def now() -> datetime:
    return datetime.now(UTC)


def transition(
    case: Case,
    target: CaseStatus,
    *,
    seq: int,
    actor: str,
    reason: str,
    data: Mapping[str, Any] | None = None,
    **changes: Any,
) -> tuple[Case, CaseEvent]:
    if target not in TRANSITIONS[case.status]:
        raise IllegalTransition(case.status, target)
    at = now()
    updated = case.model_copy(update={**changes, "status": target, "updated_at": at})
    event = CaseEvent(
        seq=seq,
        case_id=case.id,
        at=at,
        status=target,
        actor=actor,
        reason=reason,
        data=dict(data or {}),
    )
    return updated, event


def note(
    case: Case,
    *,
    seq: int,
    actor: str,
    reason: str,
    data: Mapping[str, Any] | None = None,
    **changes: Any,
) -> tuple[Case, CaseEvent]:
    at = now()
    updated = case.model_copy(update={**changes, "updated_at": at})
    event = CaseEvent(
        seq=seq,
        case_id=case.id,
        at=at,
        status=case.status,
        actor=actor,
        reason=reason,
        data=dict(data or {}),
    )
    return updated, event
