from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from relay_agents.contracts import Channel, Intent, Severity


def _jira_priorities() -> dict[Severity, str]:
    return {"sev1": "Highest", "sev2": "High", "sev3": "Medium", "sev4": "Low"}


def _snow_urgency() -> dict[Severity, str]:
    return {"sev1": "1", "sev2": "2", "sev3": "3", "sev4": "3"}


def _always_escalate() -> list[Intent]:
    return ["privacy"]


def _escalate_severities() -> list[Severity]:
    return ["sev1"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Brand(Strict):
    name: str
    primary: str
    accent: str
    logo_url: str | None = None
    voice: str = "clear, warm, concise"


class Models(Strict):
    classifier: str = "anthropic:claude-opus-5-5"
    specialist: str = "anthropic:claude-opus-5-5"


class JiraConfig(Strict):
    project: str
    issue_type: str = "Task"
    priority_map: dict[Severity, str] = Field(default_factory=_jira_priorities)
    resolve_transition_id: str | None = None
    base_url_env: str
    email_env: str
    token_env: str


class ServiceNowConfig(Strict):
    table: Literal["incident", "sn_customerservice_case"] = "incident"
    assignment_group: str | None = None
    urgency_map: dict[Severity, str] = Field(default_factory=_snow_urgency)
    resolve_fields: dict[str, str] = Field(
        default_factory=lambda: {"state": "6", "close_code": "Solution provided"}
    )
    instance_url_env: str
    client_id_env: str
    client_secret_env: str


class Tickets(Strict):
    jira: JiraConfig | None = None
    servicenow: ServiceNowConfig | None = None


class Policy(Strict):
    auto_resolve_min_confidence: Annotated[float, Field(ge=0, le=1)] = 0.75
    always_escalate_intents: list[Intent] = Field(default_factory=_always_escalate)
    escalate_severities: list[Severity] = Field(default_factory=_escalate_severities)
    max_attempts: Annotated[int, Field(ge=1, le=5)] = 2


class KbArticle(Strict):
    id: str
    title: str
    answer: str
    keywords: list[str] = Field(default_factory=list)


class TenantConfig(Strict):
    tenant: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{2,40}$")]
    brand: Brand
    channels: list[Channel]
    specialists: list[Intent]
    models: Models = Field(default_factory=Models)
    tickets: Tickets = Field(default_factory=Tickets)
    policy: Policy = Field(default_factory=Policy)
    knowledge_seed: list[KbArticle] = Field(default_factory=list)


def load_tenants(directory: Path) -> dict[str, TenantConfig]:
    tenants: dict[str, TenantConfig] = {}
    for path in sorted(directory.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        config = TenantConfig.model_validate(yaml.safe_load(path.read_text()))
        if config.tenant != path.stem:
            raise ValueError(f"{path.name} declares tenant {config.tenant!r}; file name must match")
        tenants[config.tenant] = config
    return tenants
