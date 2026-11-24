import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from relay_agents.classifier import Classifier
from relay_agents.connectors.ports import (
    TicketDraft,
    TicketPort,
    TicketWriteError,
    correlation_key,
)
from relay_agents.contracts import Classification, IntakeRequest, Intent, Resolution, TicketRef
from relay_agents.policy import Decision, assess
from relay_agents.specialists.base import Specialist, SpecialistContext, SpecialistResult
from relay_agents.store import CaseNotFound, CaseStore
from relay_agents.tenants import TenantConfig

ESCALATION_MESSAGE = (
    "We've passed your request to our support team. They have the full history, "
    "so you won't need to repeat yourself."
)


class GraphState(TypedDict, total=False):
    case_id: str
    tenant: str
    resume: bool
    classification: Classification
    result: SpecialistResult | None
    attempts: int
    decision: Decision


@dataclass(frozen=True)
class Deps:
    store: CaseStore
    classifier: Classifier
    specialists: Mapping[str, Mapping[Intent, Specialist]]
    tickets: Mapping[str, Sequence[TicketPort]]
    tenants: Mapping[str, TenantConfig]


async def _case(deps: Deps, state: GraphState) -> Any:
    case = await deps.store.get(state["tenant"], state["case_id"])
    if case is None:
        raise CaseNotFound(state["case_id"])
    return case


async def _each_ticket(deps: Deps, state: GraphState, action: str, text: str) -> list[str]:
    key = correlation_key(state["tenant"], state["case_id"])
    ports = deps.tickets.get(state["tenant"], ())
    calls = [getattr(port, action)(key, text) for port in ports]
    results = await asyncio.gather(*calls, return_exceptions=True)
    return [
        port.system
        for port, r in zip(ports, results, strict=True)
        if isinstance(r, TicketWriteError)
    ]


async def classify(state: GraphState, deps: Deps) -> dict[str, Any]:
    tenant = deps.tenants[state["tenant"]]
    case = await _case(deps, state)
    messages = await deps.store.messages(case.id)
    classification = await deps.classifier.classify(
        IntakeRequest(channel=case.channel, message=messages[0]), tenant
    )
    await deps.store.move(
        case.id,
        "triaged",
        actor="orchestrator",
        reason=f"classified as {classification.intent}",
        data={"classification": classification.model_dump(mode="json")},
        classification=classification,
    )
    return {"classification": classification}


async def open_tickets(state: GraphState, deps: Deps) -> dict[str, Any]:
    case = await _case(deps, state)
    c = state["classification"]
    draft = TicketDraft(
        correlation_key=correlation_key(case.tenant, case.id),
        title=f"[{c.severity}] {c.summary}",
        description=(
            f"{c.summary}\n\nRelay case: {case.id}\nTrace: {case.trace_id}\n"
            f"Channel: {case.channel}\nIntent: {c.intent}\nSentiment: {c.sentiment}"
        ),
        severity=c.severity,
        labels=(f"intent-{c.intent}",),
    )
    ports = deps.tickets.get(case.tenant, ())
    results = await asyncio.gather(*(p.ensure_ticket(draft) for p in ports), return_exceptions=True)
    refs = [r for r in results if isinstance(r, TicketRef)]
    pending = [
        p.system for p, r in zip(ports, results, strict=True) if not isinstance(r, TicketRef)
    ]
    await deps.store.move(
        case.id,
        "ticketed",
        actor="orchestrator",
        reason="tickets opened" if not pending else "tickets partially opened",
        data={"tickets": [r.model_dump() for r in refs], "pending": pending},
        tickets=refs,
    )
    return {}


async def run_specialist(state: GraphState, deps: Deps) -> dict[str, Any]:
    tenant = deps.tenants[state["tenant"]]
    case = await _case(deps, state)
    classification = state.get("classification") or case.classification
    specialist = (
        deps.specialists[tenant.tenant].get(classification.intent)
        if classification.intent in tenant.specialists
        else None
    )
    if specialist is None:
        return {"classification": classification, "result": None, "attempts": 0}
    if case.status == "ticketed":
        await deps.store.move(
            case.id, "in_progress", actor="orchestrator", reason=f"assigned {specialist.name}"
        )
    result = await specialist.run(
        SpecialistContext(
            case=case,
            classification=classification,
            tenant=tenant,
            messages=await deps.store.messages(case.id),
        )
    )
    events = await deps.store.events(case.tenant, case.id)
    attempts = 1 + sum(1 for e in events if e.reason == "specialist finished")
    await deps.store.note(
        case.id,
        actor=specialist.name,
        reason="specialist finished",
        data={
            "confidence": result.confidence,
            "citations": list(result.citations),
            "needs_customer_input": result.needs_customer_input,
            "prompt_version": result.prompt_version,
        },
    )
    return {"classification": classification, "result": result, "attempts": attempts}


async def assess_node(state: GraphState, deps: Deps) -> dict[str, Any]:
    tenant = deps.tenants[state["tenant"]]
    decision = assess(
        state["classification"], state.get("result"), tenant.policy, state.get("attempts", 0)
    )
    return {"decision": decision}


async def resolve(state: GraphState, deps: Deps) -> dict[str, Any]:
    result = state["result"]
    assert result is not None
    resolution = Resolution(
        kind="auto_resolved", message=result.answer, citations=list(result.citations)
    )
    await deps.store.move(
        state["case_id"],
        "resolved",
        actor="orchestrator",
        reason=state["decision"].rule,
        data={"citations": list(result.citations)},
        resolution=resolution,
        pending_question=None,
    )
    failed = await _each_ticket(
        deps, state, "resolve", f"Auto-resolved by Relay.\n\n{result.answer}"
    )
    if failed:
        await deps.store.note(
            state["case_id"],
            actor="orchestrator",
            reason="ticket sync failed",
            data={"systems": failed},
        )
    return {}


async def await_customer(state: GraphState, deps: Deps) -> dict[str, Any]:
    result = state["result"]
    assert result is not None
    await deps.store.move(
        state["case_id"],
        "awaiting_customer",
        actor="orchestrator",
        reason=state["decision"].rule,
        data={"question": result.answer},
        pending_question=result.answer,
    )
    await _each_ticket(deps, state, "add_note", f"Waiting on customer: {result.answer}")
    return {}


async def escalate(state: GraphState, deps: Deps) -> dict[str, Any]:
    result = state.get("result")
    decision = state["decision"]
    summary = result.handoff_summary if result else state["classification"].summary
    await deps.store.move(
        state["case_id"],
        "escalated",
        actor="orchestrator",
        reason=decision.rule,
        data={"handoff_summary": summary},
        resolution=Resolution(kind="escalated", message=ESCALATION_MESSAGE, citations=[]),
        pending_question=None,
    )
    failed = await _each_ticket(
        deps, state, "add_note", f"Escalated by Relay ({decision.rule}).\n\n{summary}"
    )
    if failed:
        await deps.store.note(
            state["case_id"],
            actor="orchestrator",
            reason="ticket sync failed",
            data={"systems": failed},
        )
    return {}


NODES = {
    "classify": classify,
    "open_tickets": open_tickets,
    "run_specialist": run_specialist,
    "assess": assess_node,
    "resolve": resolve,
    "await_customer": await_customer,
    "escalate": escalate,
}


def _start(state: GraphState) -> str:
    return "run_specialist" if state.get("resume") else "classify"


def _after_assess(state: GraphState) -> str:
    return state["decision"].outcome


def build_graph(deps: Deps, nodes: Mapping[str, Any] = NODES) -> Any:
    graph = StateGraph(GraphState)
    for name, fn in nodes.items():
        graph.add_node(name, partial(fn, deps=deps))
    graph.add_conditional_edges(START, _start, ["classify", "run_specialist"])
    graph.add_edge("classify", "open_tickets")
    graph.add_edge("open_tickets", "run_specialist")
    graph.add_edge("run_specialist", "assess")
    graph.add_conditional_edges(
        "assess",
        _after_assess,
        {"resolve": "resolve", "await_customer": "await_customer", "escalate": "escalate"},
    )
    for terminal in ("resolve", "await_customer", "escalate"):
        graph.add_edge(terminal, END)
    return graph.compile()
