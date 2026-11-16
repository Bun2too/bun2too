from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from relay_agents.llm import chat_model
from relay_agents.specialists.base import ProposedAction, SpecialistContext, SpecialistResult
from relay_agents.untrusted import as_untrusted

_PROMPTS = Path(__file__).parent.parent / "prompts"


class SpecialistOutput(BaseModel):
    answer: str = Field(description="Reply to the customer, in the brand voice")
    confidence: float = Field(
        ge=0, le=1, description="Probability the answer fully resolves the case"
    )
    citations: list[str] = Field(description="Knowledge article ids the answer relies on")
    needs_customer_input: bool = Field(
        description="True when only the customer can supply a missing fact"
    )
    proposed_actions: list[str] = Field(description="Action names to run, e.g. send_reset_link")
    handoff_summary: str = Field(description="Two sentences for an operator if this escalates")


class LlmSpecialist:
    def __init__(self, name: str, prompt_file: str, tools: list[BaseTool]) -> None:
        self.name = name
        self._prompt = (_PROMPTS / prompt_file).read_text()
        self._version = f"{prompt_file}/2026-11-16"
        self._tools = tools

    async def run(self, ctx: SpecialistContext) -> SpecialistResult:
        agent = create_agent(
            model=chat_model(ctx.tenant.models.specialist),
            tools=self._tools,
            system_prompt=self._prompt.format(
                brand=ctx.tenant.brand.name, voice=ctx.tenant.brand.voice
            ),
            response_format=ProviderStrategy(SpecialistOutput),
        )
        state = await agent.ainvoke(
            {"messages": [HumanMessage(as_untrusted(m).render()) for m in ctx.messages]}
        )
        out = SpecialistOutput.model_validate(state["structured_response"])
        return SpecialistResult(
            answer=out.answer,
            confidence=out.confidence,
            citations=tuple(out.citations),
            needs_customer_input=out.needs_customer_input,
            proposed_actions=tuple(ProposedAction(a, {}) for a in out.proposed_actions),
            prompt_version=self._version,
            handoff_summary=out.handoff_summary,
        )
