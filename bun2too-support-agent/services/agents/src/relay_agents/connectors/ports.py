from dataclasses import dataclass, field
from typing import Protocol

from relay_agents.contracts import Severity, TicketRef, TicketSystem


class TicketWriteError(Exception):
    pass


@dataclass(frozen=True)
class TicketDraft:
    correlation_key: str
    title: str
    description: str
    severity: Severity
    labels: tuple[str, ...] = field(default=())


def correlation_key(tenant: str, case_id: str) -> str:
    return f"relay-{tenant}-{case_id}"


class TicketPort(Protocol):
    @property
    def system(self) -> TicketSystem: ...

    async def ensure_ticket(self, draft: TicketDraft) -> TicketRef: ...

    async def add_note(self, correlation_key: str, text: str) -> None: ...

    async def resolve(self, correlation_key: str, text: str) -> None: ...
