import asyncio
import socket

import pytest

from relay_agents.__main__ import bind_host


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "127.0.0.1"), ("::", ""), ("10.0.0.5", "10.0.0.5"), ("127.0.0.1", "127.0.0.1")],
)
def test_bind_host(monkeypatch: pytest.MonkeyPatch, value: str | None, expected: str) -> None:
    if value is None:
        monkeypatch.delenv("RELAY_AGENTS_HOST", raising=False)
    else:
        monkeypatch.setenv("RELAY_AGENTS_HOST", value)
    assert bind_host() == expected


def test_all_interfaces_host_accepts_ipv4_and_ipv6(monkeypatch: pytest.MonkeyPatch) -> None:
    """Railway health-checks over IPv4 and its private network is IPv6."""
    monkeypatch.setenv("RELAY_AGENTS_HOST", "::")

    async def families() -> set[int]:
        server = await asyncio.get_running_loop().create_server(asyncio.Protocol, bind_host(), 0)
        try:
            return {sock.family for sock in server.sockets}
        finally:
            server.close()
            await server.wait_closed()

    found = asyncio.run(families())
    assert socket.AF_INET in found
    if socket.has_ipv6:
        assert socket.AF_INET6 in found
