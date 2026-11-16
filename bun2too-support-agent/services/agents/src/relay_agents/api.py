from fastapi import BackgroundTasks, FastAPI, HTTPException, Response

from relay_agents.contracts import Case, CaseEvent, CustomerReply, IntakeAccepted, IntakeCommand
from relay_agents.service import CaseService, NotAwaitingCustomer, UnknownTenant


def create_app(service: CaseService, *, offline: bool) -> FastAPI:
    app = FastAPI(title="relay-agents", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return {"ok": True, "service": "relay-agents", "offline": offline}

    @app.post("/runs/intake", response_model=IntakeAccepted)
    async def intake(
        command: IntakeCommand, background: BackgroundTasks, response: Response
    ) -> IntakeAccepted:
        try:
            accepted = await service.intake(command)
        except UnknownTenant as error:
            raise HTTPException(404, "unknown tenant") from error
        if accepted.created:
            background.add_task(service.run, command.tenant, accepted.case_id)
            response.status_code = 202
        return accepted

    @app.get("/tenants/{tenant}/cases/{case_id}", response_model=Case)
    async def get_case(tenant: str, case_id: str) -> Case:
        case = await service.deps.store.get(tenant, case_id)
        if case is None:
            raise HTTPException(404, "case not found")
        return case

    @app.get("/tenants/{tenant}/cases/{case_id}/events", response_model=list[CaseEvent])
    async def get_events(tenant: str, case_id: str, after: int = -1) -> list[CaseEvent]:
        if await service.deps.store.get(tenant, case_id) is None:
            raise HTTPException(404, "case not found")
        return await service.deps.store.events(tenant, case_id, after)

    @app.post("/tenants/{tenant}/cases/{case_id}/messages", response_model=Case, status_code=202)
    async def reply(
        tenant: str, case_id: str, body: CustomerReply, background: BackgroundTasks
    ) -> Case:
        try:
            case = await service.reply(tenant, case_id, body.message)
        except NotAwaitingCustomer as error:
            raise HTTPException(409, "case is not waiting for the customer") from error
        if case is None:
            raise HTTPException(404, "case not found")
        background.add_task(service.run, tenant, case_id, resume=True)
        return case

    return app
