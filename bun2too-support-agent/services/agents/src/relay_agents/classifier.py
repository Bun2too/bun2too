from pathlib import Path
from typing import Protocol

from relay_agents.contracts import Classification, IntakeRequest, Intent, Severity
from relay_agents.llm import chat_model, structured
from relay_agents.tenants import TenantConfig
from relay_agents.untrusted import as_untrusted

PROMPT_VERSION = "classifier/2026-11-16"
_PROMPT = (Path(__file__).parent / "prompts" / "classifier.md").read_text()


class Classifier(Protocol):
    async def classify(self, intake: IntakeRequest, tenant: TenantConfig) -> Classification: ...


class LlmClassifier:
    async def classify(self, intake: IntakeRequest, tenant: TenantConfig) -> Classification:
        model = structured(chat_model(tenant.models.classifier), Classification)
        system = _PROMPT.format(brand=tenant.brand.name, intents=", ".join(tenant.specialists))
        result = await model.ainvoke(
            [("system", system), ("user", as_untrusted(intake.message).render())]
        )
        return Classification.model_validate(result)


_KEYWORDS: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    (
        "privacy",
        ("delete my", "personal data", "gdpr", "ccpa", "consent", "unsubscribe", "privacy"),
    ),
    ("identity", ("log in", "login", "password", "mfa", "sso", "locked", "sign in", "reset")),
    ("integration", ("api", "webhook", "401", "500", "integration", "sdk", "pipeline", "sync")),
    ("commerce", ("order", "refund", "invoice", "billing", "charge", "shipping", "return")),
    ("knowledge", ("how do", "how can", "what is", "where", "inquiry", "faq", "can i")),
)
_SEV1 = ("outage", "down for everyone", "data breach", "security incident")
_NEGATIVE = ("angry", "unacceptable", "terrible", "frustrated", "again", "still")


class KeywordClassifier:
    async def classify(self, intake: IntakeRequest, tenant: TenantConfig) -> Classification:
        text = intake.message.lower()
        intent: Intent = next(
            (
                i
                for i, words in _KEYWORDS
                if i in tenant.specialists and any(w in text for w in words)
            ),
            "other",
        )
        severity: Severity = "sev1" if any(w in text for w in _SEV1) else "sev3"
        return Classification(
            intent=intent,
            severity=severity,
            sentiment="negative" if any(w in text for w in _NEGATIVE) else "neutral",
            summary=intake.message[:140],
            language="en",
        )
