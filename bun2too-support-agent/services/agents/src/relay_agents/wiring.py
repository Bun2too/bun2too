import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx

from relay_agents.classifier import Classifier, KeywordClassifier, LlmClassifier
from relay_agents.connectors.fakes import InMemoryTicketPort
from relay_agents.connectors.jira import JiraTicketPort
from relay_agents.connectors.ports import TicketPort
from relay_agents.connectors.servicenow import ClientCredentials, ServiceNowTicketPort
from relay_agents.contracts import Intent
from relay_agents.graph import Deps
from relay_agents.knowledge import InMemoryKnowledgeBase
from relay_agents.llm import check_models
from relay_agents.service import CaseService
from relay_agents.specialists import build_llm_specialists, build_offline_specialists
from relay_agents.specialists.base import Specialist
from relay_agents.store import InMemoryCaseStore
from relay_agents.tenants import TenantConfig, load_tenants

DEFAULT_TENANTS_DIR = Path(__file__).resolve().parents[4] / "tenants"


def _live_tickets(tenant: TenantConfig, env: Mapping[str, str]) -> list[TicketPort]:
    ports: list[TicketPort] = []
    jira = tenant.tickets.jira
    if jira:
        client = httpx.AsyncClient(auth=(env[jira.email_env], env[jira.token_env]), timeout=10.0)
        ports.append(JiraTicketPort(client, env[jira.base_url_env], jira))
    snow = tenant.tickets.servicenow
    if snow:
        instance = env[snow.instance_url_env]
        auth = ClientCredentials(instance, env[snow.client_id_env], env[snow.client_secret_env])
        client = httpx.AsyncClient(auth=auth, timeout=10.0)
        ports.append(ServiceNowTicketPort(client, instance, snow))
    return ports


def build_deps(tenants: Mapping[str, TenantConfig], env: Mapping[str, str]) -> Deps:
    offline = env.get("RELAY_OFFLINE") == "1"
    if not offline:
        check_models(
            {m for t in tenants.values() for m in (t.models.classifier, t.models.specialist)}, env
        )
    specialists: dict[str, Mapping[Intent, Specialist]] = {}
    tickets: dict[str, Sequence[TicketPort]] = {}
    for slug, tenant in tenants.items():
        kb = InMemoryKnowledgeBase(tenant.knowledge_seed)
        specialists[slug] = build_offline_specialists(kb) if offline else build_llm_specialists(kb)
        tickets[slug] = (
            [InMemoryTicketPort("jira"), InMemoryTicketPort("servicenow")]
            if offline
            else _live_tickets(tenant, env)
        )
    classifier: Classifier = KeywordClassifier() if offline else LlmClassifier()
    return Deps(
        store=InMemoryCaseStore(),
        classifier=classifier,
        specialists=specialists,
        tickets=tickets,
        tenants=tenants,
    )


def build_service(env: Mapping[str, str] = os.environ) -> CaseService:
    tenants_dir = Path(env.get("RELAY_TENANTS_DIR", str(DEFAULT_TENANTS_DIR)))
    return CaseService(build_deps(load_tenants(tenants_dir), env))
