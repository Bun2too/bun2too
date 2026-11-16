from typing import Annotated
from pydantic import BaseModel, Field, StringConstraints


class CampaignRequest(BaseModel):
    campaign_key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    brief: str = Field(min_length=1, max_length=20000)
    audience: str = Field(default="Not specified; identify assumptions", max_length=4000)
    channels: list[str] = Field(default_factory=lambda: ["facebook"], min_length=1, max_length=10)
    brand_guidelines: str = Field(default="Clear, factual, helpful bun2too voice.", max_length=8000)
    source_material: str = Field(default="", max_length=30000)
    jira_issue_keys: list[Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*-[0-9]+$")]] = Field(default_factory=list, max_length=20)
    confluence_page_ids: list[Annotated[str, StringConstraints(pattern=r"^[0-9]+$")]] = Field(default_factory=list, max_length=10)
    lesson_run_ids: list[str] = Field(default_factory=list, max_length=10)


class BacklogItem(BaseModel):
    work_key: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,40}$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=10000)
    acceptance_criteria: list[str]
    owner_role: str
    dependencies: list[str] = Field(default_factory=list)


class AgentDeliverable(BaseModel):
    approved_for_publication: bool = False
    summary: str
    decisions: list[str]
    evidence: list[str]
    assumptions: list[str]
    risks: list[str]
    work_items: list[BacklogItem] = Field(default_factory=list, max_length=20)
    deliverable: str


class LessonRequest(BaseModel):
    lesson: str = Field(min_length=1, max_length=4000)
    evidence: str = Field(min_length=1, max_length=4000)
    reviewed_by: str = Field(min_length=1, max_length=200)


class GenerationRequest(BaseModel):
    article_text: str = Field(min_length=1, max_length=30000)
    topic_context: str = Field(default="", max_length=8000)


class SocialPost(BaseModel):
    channel: str
    text: str = Field(min_length=1)
    suggested_schedule: str = "Unscheduled; human to confirm timezone and date"
    asset_brief: str = ""


class Article(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=100, max_length=20000)
    source_urls: list[str] = Field(default_factory=list, max_length=10)


class MarketingArtifact(BaseModel):
    articles: list[Article] = Field(default_factory=list, max_length=1)
    campaign_plan: str
    requirements: str
    creative_brief: str
    engineering_plan: str
    delivery_plan: str
    measurement_plan: str
    posts: list[SocialPost] = Field(min_length=1)
    blockers: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    # Supply the whole edited artifact, or omit to approve the saved version.
    artifact: MarketingArtifact | None = None
