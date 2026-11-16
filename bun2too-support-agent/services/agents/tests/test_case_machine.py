from datetime import UTC, datetime

import pytest

from relay_agents.case_machine import TRANSITIONS, IllegalTransition, transition
from relay_agents.contracts import Case, CaseStatus


def make_case(status: CaseStatus) -> Case:
    at = datetime(2026, 11, 16, tzinfo=UTC)
    return Case(
        id="case_1",
        tenant="acme",
        status=status,
        channel="web_widget",
        created_at=at,
        updated_at=at,
        trace_id="t",
        classification=None,
        tickets=[],
        resolution=None,
        pending_question=None,
    )


EDGES = [(src, dst) for src, targets in TRANSITIONS.items() for dst in sorted(targets)]
ALL: list[CaseStatus] = list(TRANSITIONS)


@pytest.mark.parametrize(("src", "dst"), EDGES)
def test_every_documented_edge_is_allowed(src: CaseStatus, dst: CaseStatus) -> None:
    updated, event = transition(make_case(src), dst, seq=3, actor="test", reason="edge")
    assert updated.status == dst
    assert (event.seq, event.status, event.actor) == (3, dst, "test")


@pytest.mark.parametrize(
    ("src", "dst"),
    [(s, d) for s in ALL for d in ALL if d not in TRANSITIONS[s]],
)
def test_every_other_edge_is_rejected(src: CaseStatus, dst: CaseStatus) -> None:
    with pytest.raises(IllegalTransition):
        transition(make_case(src), dst, seq=1, actor="test", reason="illegal")


def test_rejected_is_terminal() -> None:
    assert TRANSITIONS["rejected"] == frozenset()
