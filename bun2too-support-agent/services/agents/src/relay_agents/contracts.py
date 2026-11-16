"""Pydantic mirror of packages/contracts. test_contract_parity.py keeps the two in step."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

Channel = Literal["web_widget", "a2a", "email", "marketplace", "retail"]
Intent = Literal["knowledge", "identity", "integration", "commerce", "privacy", "other"]
Severity = Literal["sev1", "sev2", "sev3", "sev4"]
Sentiment = Literal["negative", "neutral", "positive"]
CaseStatus = Literal[
    "received",
    "triaged",
    "ticketed",
    "in_progress",
    "awaiting_customer",
    "escalated",
    "resolved",
    "rejected",
]
TicketSystem = Literal["jira", "servicenow"]

SETTLED_STATUSES: frozenset[CaseStatus] = frozenset(
    {"awaiting_customer", "escalated", "resolved", "rejected"}
)

MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)
]


class WireModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True
    )


class Customer(WireModel):
    id: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    email: Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")] | None = None
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    locale: Annotated[str, StringConstraints(min_length=2, max_length=35)] | None = None


class IntakeRequest(WireModel):
    channel: Channel
    message: MessageText
    subject: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
        | None
    ) = None
    customer: Customer = Field(default_factory=Customer)
    metadata: dict[
        Annotated[str, StringConstraints(max_length=64)],
        Annotated[str, StringConstraints(max_length=500)],
    ] = Field(default_factory=dict)


class IntakeCommand(WireModel):
    tenant: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{2,40}$")]
    idempotency_key: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    intake: IntakeRequest


class CustomerReply(WireModel):
    message: MessageText


class Classification(WireModel):
    intent: Intent
    severity: Severity
    sentiment: Sentiment
    summary: str
    language: str


class TicketRef(WireModel):
    system: TicketSystem
    key: str
    url: str


class Resolution(WireModel):
    kind: Literal["auto_resolved", "escalated", "rejected"]
    message: str
    citations: list[str]


class Case(WireModel):
    id: str
    tenant: str
    status: CaseStatus
    channel: Channel
    created_at: datetime
    updated_at: datetime
    trace_id: str
    classification: Classification | None
    tickets: list[TicketRef]
    resolution: Resolution | None
    pending_question: str | None


class CaseEvent(WireModel):
    seq: Annotated[int, Field(ge=0)]
    case_id: str
    at: datetime
    status: CaseStatus
    actor: str
    reason: str
    data: dict[str, Any]


class IntakeAccepted(WireModel):
    case_id: str
    status: CaseStatus
    trace_id: str
    created: bool
