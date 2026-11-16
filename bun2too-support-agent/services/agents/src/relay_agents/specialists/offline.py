from relay_agents.knowledge import KnowledgeBase
from relay_agents.specialists.base import SpecialistContext, SpecialistResult

PROMPT_VERSION = "offline/knowledge-lookup"


class KnowledgeLookupSpecialist:
    """Deterministic specialist for offline runs and tests: answers only from the knowledge base."""

    def __init__(self, name: str, kb: KnowledgeBase, min_score: float = 0.5) -> None:
        self.name = name
        self._kb = kb
        self._min_score = min_score

    async def run(self, ctx: SpecialistContext) -> SpecialistResult:
        hits = await self._kb.search(" ".join(ctx.messages))
        best = hits[0] if hits else None
        if best is None or best.score < self._min_score:
            return SpecialistResult(
                answer="",
                confidence=0.2,
                prompt_version=PROMPT_VERSION,
                handoff_summary=f"No knowledge article matched: {ctx.classification.summary}",
            )
        return SpecialistResult(
            answer=best.article.answer,
            confidence=0.9,
            citations=(best.article.id,),
            prompt_version=PROMPT_VERSION,
            handoff_summary=f"Answered from {best.article.id}",
        )
