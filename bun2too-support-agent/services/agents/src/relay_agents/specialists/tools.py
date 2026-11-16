from langchain_core.tools import BaseTool, tool

from relay_agents.knowledge import KnowledgeBase


def knowledge_tools(kb: KnowledgeBase) -> list[BaseTool]:
    @tool
    async def search_kb(query: str) -> str:
        """Search the tenant's approved knowledge base. Returns article ids, titles and answers."""
        hits = await kb.search(query)
        if not hits:
            return "No matching articles."
        return "\n\n".join(f"[{h.article.id}] {h.article.title}\n{h.article.answer}" for h in hits)

    return [search_kb]
