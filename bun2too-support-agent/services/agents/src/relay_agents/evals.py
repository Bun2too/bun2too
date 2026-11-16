import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from relay_agents.contracts import CaseStatus, Channel, IntakeCommand, IntakeRequest, Intent
from relay_agents.service import CaseService
from relay_agents.tenants import load_tenants
from relay_agents.wiring import DEFAULT_TENANTS_DIR, build_deps

GOLDEN = Path(__file__).resolve().parents[4] / "evals" / "intake-golden.jsonl"


class GoldenRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    tenant: str
    channel: Channel
    message: str
    expected_intent: Intent
    expected_status: CaseStatus


async def run(rows: list[GoldenRow]) -> dict[str, object]:
    service = CaseService(build_deps(load_tenants(DEFAULT_TENANTS_DIR), os.environ))
    intent_ok = status_ok = 0
    misses: list[dict[str, str]] = []
    confusion: Counter[str] = Counter()
    for row in rows:
        accepted = await service.intake(
            IntakeCommand(
                tenant=row.tenant,
                idempotency_key=f"eval-{row.id}",
                intake=IntakeRequest(channel=row.channel, message=row.message),
            )
        )
        await service.run(row.tenant, accepted.case_id)
        case = await service.deps.store.get(row.tenant, accepted.case_id)
        assert case is not None
        got_intent = case.classification.intent if case.classification else "none"
        confusion[f"{row.expected_intent}->{got_intent}"] += 1
        intent_ok += got_intent == row.expected_intent
        status_ok += case.status == row.expected_status
        if got_intent != row.expected_intent or case.status != row.expected_status:
            misses.append({"id": row.id, "intent": got_intent, "status": case.status})
    n = len(rows)
    return {
        "rows": n,
        "intent_accuracy": round(intent_ok / n, 3),
        "outcome_accuracy": round(status_ok / n, 3),
        "misses": misses,
        "confusion": dict(sorted(confusion.items())),
    }


def main() -> None:
    rows = [GoldenRow.model_validate_json(line) for line in GOLDEN.read_text().splitlines() if line]
    report = asyncio.run(run(rows))
    print(json.dumps(report, indent=2))
    floor = float(os.environ.get("RELAY_EVAL_MIN", "0.8"))
    if float(str(report["intent_accuracy"])) < floor:
        sys.exit(1)


if __name__ == "__main__":
    main()
