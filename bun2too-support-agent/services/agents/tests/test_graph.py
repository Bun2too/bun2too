from dataclasses import replace
from typing import NoReturn

import anthropic
import httpx2
import pytest

from relay_agents.contracts import IntakeCommand, IntakeRequest, Intent
from relay_agents.graph import Deps
from relay_agents.service import CaseService
from relay_agents.specialists.base import Specialist, SpecialistContext, SpecialistResult

from .conftest import fake_ports


async def submit(service: CaseService, message: str, key: str = "k1") -> str:
    accepted = await service.intake(
        IntakeCommand(
            tenant="bun2too",
            idempotency_key=key,
            intake=IntakeRequest(channel="web_widget", message=message),
        )
    )
    await service.run("bun2too", accepted.case_id)
    return accepted.case_id


async def test_knowledge_question_is_auto_resolved_with_both_tickets(
    service: CaseService, deps: Deps
) -> None:
    case_id = await submit(service, "How do I send a private inquiry?")

    case = await deps.store.get("bun2too", case_id)
    assert case is not None
    assert case.status == "resolved"
    assert case.resolution is not None
    assert case.resolution.citations == ["kb-private-inquiry"]
    assert {t.system for t in case.tickets} == {"jira", "servicenow"}
    statuses = [e.status for e in await deps.store.events("bun2too", case_id)]
    assert [s for i, s in enumerate(statuses) if i == 0 or s != statuses[i - 1]] == [
        "received",
        "triaged",
        "ticketed",
        "in_progress",
        "resolved",
    ]
    assert all(p.tickets[next(iter(p.tickets))].resolved_with for p in fake_ports(deps))


async def test_privacy_request_escalates_with_handoff_on_both_tickets(
    service: CaseService, deps: Deps
) -> None:
    case_id = await submit(service, "Please delete my personal data")

    case = await deps.store.get("bun2too", case_id)
    assert case is not None
    assert case.status == "escalated"
    last = (await deps.store.events("bun2too", case_id))[-1]
    assert last.reason == "always_escalate_intent:privacy"
    for port in fake_ports(deps):
        (ticket,) = port.tickets.values()
        assert ticket.notes
        assert ticket.notes[-1].startswith("Escalated by Relay")


async def test_question_without_knowledge_escalates_on_low_confidence(
    service: CaseService, deps: Deps
) -> None:
    case_id = await submit(service, "What is the price of a CDP audit?")

    events = await deps.store.events("bun2too", case_id)
    assert events[-1].status == "escalated"
    assert events[-1].reason == "low_confidence"


async def test_repeated_intake_returns_same_case_and_opens_no_new_tickets(
    service: CaseService, deps: Deps
) -> None:
    first = await submit(service, "How do I send a private inquiry?", key="same")
    second = await service.intake(
        IntakeCommand(
            tenant="bun2too",
            idempotency_key="same",
            intake=IntakeRequest(channel="web_widget", message="How do I send a private inquiry?"),
        )
    )
    assert second.case_id == first
    assert not second.created
    assert [p.creates for p in fake_ports(deps)] == [1, 1]


class AskThenAnswer:
    name = "knowledge_agent"

    async def run(self, ctx: SpecialistContext) -> SpecialistResult:
        if len(ctx.messages) == 1:
            return SpecialistResult(
                answer="Which email address did you use?", confidence=0.5, needs_customer_input=True
            )
        return SpecialistResult(answer="Found it, resent.", confidence=0.95, citations=("kb-x",))


async def test_customer_reply_resumes_the_same_case(deps: Deps) -> None:
    asking: dict[Intent, Specialist] = {"knowledge": AskThenAnswer()}
    service = CaseService(replace(deps, specialists={"bun2too": asking}))
    case_id = await submit(service, "How do I send a private inquiry?")

    waiting = await deps.store.get("bun2too", case_id)
    assert waiting is not None
    assert waiting.status == "awaiting_customer"
    assert waiting.pending_question == "Which email address did you use?"

    await service.reply("bun2too", case_id, "me@example.com")
    await service.run("bun2too", case_id, resume=True)

    done = await deps.store.get("bun2too", case_id)
    assert done is not None
    assert done.status == "resolved"
    assert done.pending_question is None


class FailingClassifier:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def classify(self, *args: object, **kwargs: object) -> NoReturn:
        raise self.error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            anthropic.APIStatusError(
                "payment required: secret body",
                response=httpx2.Response(402, request=httpx2.Request("POST", "https://x.test")),
                body=None,
            ),
            {"error": "APIStatusError", "status": 402},
        ),
        (RuntimeError("secret detail"), {"error": "RuntimeError"}),
    ],
)
async def test_failed_run_records_the_error_class_and_http_status_only(
    deps: Deps, error: Exception, expected: dict[str, object]
) -> None:
    service = CaseService(replace(deps, classifier=FailingClassifier(error)))
    case_id = await submit(service, "How do I send a private inquiry?")

    events = await deps.store.events("bun2too", case_id)
    assert events[-1].reason == "run failed"
    assert events[-1].data == expected
