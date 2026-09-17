"""Small deterministic cleaners for untrusted provider content."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from app.config.settings import MAX_SIGNAL_CONTENT

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|password|secret)\b\s*[:=]\s*[^\s,;]+"
)
TRACKING_RE = re.compile(r"https?://\S*(?:utm_[a-z]+|tracking|unsubscribe)\S*", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"[ \t]+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.ignored += 1
        elif tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1
        elif tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return html.unescape("".join(parser.parts))


def clean_text(value: str, *, email: bool = False, limit: int = MAX_SIGNAL_CONTENT) -> str:
    """Redact common secrets/PII, quoted email history, and excess whitespace."""
    value = value.replace("\x00", "")
    if email:
        kept: list[str] = []
        for line in value.splitlines():
            stripped = line.strip()
            if stripped.startswith(">") or re.match(r"^On .+ wrote:$", stripped):
                break
            if stripped in {"--", "-- ", "Sent from my iPhone", "Sent from my Android"}:
                break
            kept.append(line)
        value = "\n".join(kept)
    value = SECRET_RE.sub(r"\1=[redacted]", value)
    value = EMAIL_RE.sub("[email redacted]", value)
    value = TRACKING_RE.sub("[link removed]", value)
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()[:limit]


def clean_title(value: str, limit: int = 160) -> str:
    return clean_text(value, limit=limit).replace("\n", " ") or "Untitled source"
