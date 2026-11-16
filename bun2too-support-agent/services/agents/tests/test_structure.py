from pathlib import Path
from typing import Any

import pytest

from relay_agents.graph import NODES, Deps, build_graph
from relay_agents.tenants import TenantConfig

SRC = Path(__file__).resolve().parents[1] / "src"


def test_source_never_names_a_tenant(tenants: dict[str, TenantConfig]) -> None:
    offenders = [
        f"{path.relative_to(SRC)} mentions {slug!r}"
        for path in SRC.rglob("*.py")
        for slug in tenants
        if f'"{slug}"' in path.read_text() or f"'{slug}'" in path.read_text()
    ]
    assert offenders == []


def test_build_graph_rejects_untraced_nodes(deps: Deps) -> None:
    async def bare(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
        return {}

    with pytest.raises(TypeError, match="traced_node"):
        build_graph(deps, {**NODES, "classify": bare})


def test_every_tenant_file_parses(tenants: dict[str, TenantConfig]) -> None:
    assert "bun2too" in tenants
    for tenant in tenants.values():
        assert set(tenant.specialists) <= {
            "knowledge",
            "identity",
            "integration",
            "commerce",
            "privacy",
        }
