from pathlib import Path

import pytest

from relay_agents.connectors.fakes import InMemoryTicketPort
from relay_agents.graph import Deps
from relay_agents.service import CaseService
from relay_agents.tenants import TenantConfig, load_tenants
from relay_agents.wiring import build_deps

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def tenants() -> dict[str, TenantConfig]:
    return load_tenants(REPO / "tenants")


@pytest.fixture
def deps(tenants: dict[str, TenantConfig]) -> Deps:
    return build_deps(tenants, {"RELAY_OFFLINE": "1"})


@pytest.fixture
def service(deps: Deps) -> CaseService:
    return CaseService(deps)


def fake_ports(deps: Deps, tenant: str = "bun2too") -> list[InMemoryTicketPort]:
    ports = list(deps.tickets[tenant])
    assert all(isinstance(p, InMemoryTicketPort) for p in ports)
    return [p for p in ports if isinstance(p, InMemoryTicketPort)]
