from dataclasses import dataclass
from typing import Literal

from relay_agents.contracts import Classification
from relay_agents.specialists.base import SpecialistResult
from relay_agents.tenants import Policy

Outcome = Literal["resolve", "await_customer", "escalate"]


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    rule: str


def assess(
    classification: Classification,
    result: SpecialistResult | None,
    policy: Policy,
    attempts: int,
) -> Decision:
    if classification.intent in policy.always_escalate_intents:
        return Decision("escalate", f"always_escalate_intent:{classification.intent}")
    if classification.severity in policy.escalate_severities:
        return Decision("escalate", f"escalate_severity:{classification.severity}")
    if result is None:
        return Decision("escalate", "no_specialist")
    if result.guardrail_trip:
        return Decision("escalate", f"guardrail:{result.guardrail_trip}")
    if result.needs_customer_input:
        if attempts >= policy.max_attempts:
            return Decision("escalate", "max_attempts")
        return Decision("await_customer", "needs_customer_input")
    if result.confidence < policy.auto_resolve_min_confidence:
        return Decision("escalate", "low_confidence")
    if classification.intent == "knowledge" and not result.citations:
        return Decision("escalate", "no_citation")
    return Decision("resolve", "confident_answer")
