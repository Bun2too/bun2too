from pydantic import BaseModel, Field


class CampaignRequest(BaseModel):
    brief: str = Field(min_length=1, max_length=20000)
    audience: str = Field(default="Not specified; identify assumptions", max_length=4000)
    channels: list[str] = Field(default_factory=lambda: ["facebook"], min_length=1, max_length=10)
    brand_guidelines: str = Field(default="Clear, factual, helpful bun2too voice.", max_length=8000)
    source_material: str = Field(default="", max_length=30000)


class GenerationRequest(BaseModel):
    article_text: str = Field(min_length=1, max_length=30000)
    topic_context: str = Field(default="", max_length=8000)


class SocialPost(BaseModel):
    channel: str
    text: str = Field(min_length=1)
    suggested_schedule: str = "Unscheduled; human to confirm timezone and date"
    asset_brief: str = ""


class MarketingArtifact(BaseModel):
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
