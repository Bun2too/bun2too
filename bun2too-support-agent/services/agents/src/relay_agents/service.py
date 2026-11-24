import logging
import uuid

from opentelemetry.trace import Status, StatusCode

from relay_agents.contracts import Case, IntakeAccepted, IntakeCommand
from relay_agents.graph import Deps, GraphState, build_graph
from relay_agents.telemetry import (
    ATTR_CASE_ID,
    ATTR_TENANT,
    ATTR_TENANT_METADATA,
    ATTR_THREAD_ID,
    current_trace_id,
    tracer,
)

log = logging.getLogger("relay.agents")


class UnknownTenant(Exception):
    pass


class NotAwaitingCustomer(Exception):
    pass


class CaseService:
    def __init__(self, deps: Deps) -> None:
        self._deps = deps
        self._graph = build_graph(deps)

    @property
    def deps(self) -> Deps:
        return self._deps

    async def intake(self, command: IntakeCommand) -> IntakeAccepted:
        if command.tenant not in self._deps.tenants:
            raise UnknownTenant(command.tenant)
        case, created = await self._deps.store.open(
            tenant=command.tenant,
            idempotency_key=command.idempotency_key,
            channel=command.intake.channel,
            message=command.intake.message,
            trace_id=current_trace_id() or uuid.uuid4().hex,
        )
        return IntakeAccepted(
            case_id=case.id, status=case.status, trace_id=case.trace_id, created=created
        )

    async def run(self, tenant: str, case_id: str, *, resume: bool = False) -> None:
        with tracer.start_as_current_span("relay.case.run") as span:
            span.set_attribute(ATTR_TENANT, tenant)
            span.set_attribute(ATTR_CASE_ID, case_id)
            span.set_attribute(ATTR_THREAD_ID, case_id)
            span.set_attribute(ATTR_TENANT_METADATA, tenant)
            state: GraphState = {"case_id": case_id, "tenant": tenant, "resume": resume}
            # LangSmith copies no metadata from a parent run to its children, so every
            # LangChain run in the graph gets the thread from the config it inherits.
            config = {"metadata": {"thread_id": case_id, "tenant": tenant}}
            try:
                await self._graph.ainvoke(state, config=config)
            except Exception as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, type(error).__name__))
                log.exception("case run failed", extra={"case_id": case_id, "tenant": tenant})
                await self._deps.store.note(
                    case_id,
                    actor="orchestrator",
                    reason="run failed",
                    data=_failure(error),
                )

    async def reply(self, tenant: str, case_id: str, message: str) -> Case | None:
        case = await self._deps.store.get(tenant, case_id)
        if case is None:
            return None
        if case.status != "awaiting_customer":
            raise NotAwaitingCustomer(case.status)
        await self._deps.store.add_message(case_id, message)
        return await self._deps.store.move(
            case_id,
            "in_progress",
            actor="customer",
            reason="customer replied",
            pending_question=None,
        )


def _failure(error: Exception) -> dict[str, object]:
    """The exception class and, for an HTTP error, its status code: never the message,
    which can carry a provider's response body."""
    status = getattr(error, "status_code", None)
    return {"error": type(error).__name__} | ({"status": status} if isinstance(status, int) else {})
