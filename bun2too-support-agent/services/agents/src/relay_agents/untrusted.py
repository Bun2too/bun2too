import re
from dataclasses import dataclass

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


@dataclass(frozen=True)
class Untrusted:
    text: str

    def render(self) -> str:
        safe = self.text.replace("</customer_message", "<\\/customer_message")
        return f"<customer_message>\n{safe}\n</customer_message>"


def as_untrusted(text: str) -> Untrusted:
    return Untrusted(text)


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _CARD.sub("[card]", text)
    return _PHONE.sub("[phone]", text)
