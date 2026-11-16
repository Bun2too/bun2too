from collections.abc import Mapping

from relay_agents.contracts import Intent
from relay_agents.knowledge import KnowledgeBase
from relay_agents.specialists.base import Specialist
from relay_agents.specialists.llm_specialist import LlmSpecialist
from relay_agents.specialists.offline import KnowledgeLookupSpecialist
from relay_agents.specialists.tools import knowledge_tools

PROMPT_FILES: Mapping[Intent, str] = {
    "knowledge": "knowledge.md",
    "identity": "identity.md",
    "integration": "integration.md",
    "commerce": "commerce.md",
    "privacy": "privacy.md",
}


def build_llm_specialists(kb: KnowledgeBase) -> dict[Intent, Specialist]:
    tools = knowledge_tools(kb)
    return {
        intent: LlmSpecialist(f"{intent}_agent", prompt, tools)
        for intent, prompt in PROMPT_FILES.items()
    }


def build_offline_specialists(kb: KnowledgeBase) -> dict[Intent, Specialist]:
    return {intent: KnowledgeLookupSpecialist(f"{intent}_agent", kb) for intent in PROMPT_FILES}
