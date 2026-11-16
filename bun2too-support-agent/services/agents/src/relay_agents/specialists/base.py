from dataclasses import dataclass, field
from typing import Protocol

from relay_agents.contracts import Case, Classification
from relay_agents.tenants import TenantConfig


@dataclass(frozen=True)
class ProposedAction:
    name: str
    arguments: dict[str, str]


@dataclass(frozen=True)
class SpecialistResult:
    answer: str
    confidence: float
    citations: tuple[str, ...] = ()
    needs_customer_input: bool = False
    proposed_actions: tuple[ProposedAction, ...] = ()
    guardrail_trip: str | None = None
    prompt_version: str = ""
    handoff_summary: str = ""


@dataclass(frozen=True)
class SpecialistContext:
    case: Case
    classification: Classification
    tenant: TenantConfig
    messages: list[str] = field(default_factory=list)


class Specialist(Protocol):
    name: str

    async def run(self, ctx: SpecialistContext) -> SpecialistResult: ...
