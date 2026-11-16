from dataclasses import dataclass, field

from relay_agents.connectors.ports import TicketDraft, TicketWriteError
from relay_agents.contracts import TicketRef, TicketSystem


@dataclass
class FakeTicket:
    ref: TicketRef
    draft: TicketDraft
    notes: list[str] = field(default_factory=list)
    resolved_with: str | None = None


class InMemoryTicketPort:
    def __init__(self, system: TicketSystem) -> None:
        self.system = system
        self.tickets: dict[str, FakeTicket] = {}
        self.creates = 0

    async def ensure_ticket(self, draft: TicketDraft) -> TicketRef:
        existing = self.tickets.get(draft.correlation_key)
        if existing:
            return existing.ref
        self.creates += 1
        prefix = "SUP" if self.system == "jira" else "INC"
        key = f"{prefix}-{self.creates:05d}"
        ref = TicketRef(system=self.system, key=key, url=f"https://{self.system}.invalid/{key}")
        self.tickets[draft.correlation_key] = FakeTicket(ref=ref, draft=draft)
        return ref

    async def add_note(self, correlation_key: str, text: str) -> None:
        self._require(correlation_key).notes.append(text)

    async def resolve(self, correlation_key: str, text: str) -> None:
        self._require(correlation_key).resolved_with = text

    def _require(self, correlation_key: str) -> FakeTicket:
        ticket = self.tickets.get(correlation_key)
        if ticket is None:
            raise TicketWriteError(f"no fake {self.system} ticket for {correlation_key}")
        return ticket
