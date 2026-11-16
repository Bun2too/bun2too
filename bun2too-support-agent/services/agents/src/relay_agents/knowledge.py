import re
from dataclasses import dataclass
from typing import Protocol

from relay_agents.tenants import KbArticle

_WORD = re.compile(r"[a-z0-9]+")
_STOP_WORDS = """
a an and are can do does for how i in is it me my of on or the to what with you
"""
_STOP = frozenset(_STOP_WORDS.split())


@dataclass(frozen=True)
class KbHit:
    article: KbArticle
    score: float


class KnowledgeBase(Protocol):
    async def search(self, query: str, limit: int = 3) -> list[KbHit]: ...


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


class InMemoryKnowledgeBase:
    def __init__(self, articles: list[KbArticle]) -> None:
        self._index = [(a, _terms(f"{a.title} {' '.join(a.keywords)}")) for a in articles]

    async def search(self, query: str, limit: int = 3) -> list[KbHit]:
        terms = _terms(query)
        if not terms:
            return []
        hits = [
            KbHit(article, len(terms & index) / len(terms))
            for article, index in self._index
            if terms & index
        ]
        return sorted(hits, key=lambda h: h.score, reverse=True)[:limit]
