import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from relay_agents import contracts

SCHEMAS = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "schema"
MODELS: dict[str, type[BaseModel]] = {
    "IntakeRequest": contracts.IntakeRequest,
    "IntakeCommand": contracts.IntakeCommand,
    "IntakeAccepted": contracts.IntakeAccepted,
    "CustomerReply": contracts.CustomerReply,
    "Case": contracts.Case,
    "CaseEvent": contracts.CaseEvent,
}


def ts_schema(name: str) -> dict[str, object]:
    return dict(json.loads((SCHEMAS / f"{name}.schema.json").read_text()))


@pytest.mark.parametrize("name", MODELS)
def test_field_names_match_typescript(name: str) -> None:
    ts_fields = set(dict(ts_schema(name)["properties"]))  # type: ignore[call-overload]
    py_fields = set(MODELS[name].model_json_schema(by_alias=True)["properties"])
    assert py_fields == ts_fields


FIXTURES = [
    ("IntakeRequest", {"channel": "web_widget", "message": "help"}),
    (
        "IntakeRequest",
        {
            "channel": "email",
            "message": "x",
            "customer": {"email": "a@b.co"},
            "metadata": {"order": "1"},
        },
    ),
    (
        "IntakeCommand",
        {"tenant": "acme", "idempotencyKey": "k", "intake": {"channel": "a2a", "message": "m"}},
    ),
]
INVALID = [
    ("IntakeRequest", {"channel": "fax", "message": "help"}),
    ("IntakeRequest", {"channel": "email", "message": "x", "priority": "high"}),
    (
        "IntakeCommand",
        {
            "tenant": "Not A Slug",
            "idempotencyKey": "k",
            "intake": {"channel": "a2a", "message": "m"},
        },
    ),
]


@pytest.mark.parametrize(("name", "payload"), FIXTURES)
def test_both_sides_accept(name: str, payload: dict[str, object]) -> None:
    Draft202012Validator(ts_schema(name)).validate(payload)
    MODELS[name].model_validate(payload)


@pytest.mark.parametrize(("name", "payload"), INVALID)
def test_both_sides_reject(name: str, payload: dict[str, object]) -> None:
    assert not Draft202012Validator(ts_schema(name)).is_valid(payload)
    with pytest.raises(ValueError, match="validation error"):
        MODELS[name].model_validate(payload)
