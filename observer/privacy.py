import re

from .config import Settings
from .models import Window


class Privacy:
    def __init__(self, settings: Settings):
        self.settings = settings

    def excluded(self, window: Window) -> bool:
        return any(x.strip().casefold() in window.application.casefold()
                   for x in self.settings.excluded_apps if x.strip()) or any(
            x.strip().casefold() in window.title.casefold()
            for x in self.settings.excluded_titles if x.strip())

    def redact(self, text: str) -> str:
        for value in sorted(self.settings.redactions, key=len, reverse=True):
            if value.strip():
                text = re.sub(re.escape(value), "[REDACTED]", text, flags=re.IGNORECASE)
        text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[EMAIL]", text, flags=re.I)
        text = re.sub(r"\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_\-]{12,}", "[TOKEN]", text)
        text = re.sub(r"(?i)\bBearer\s+[\w.\-]+", "Bearer [TOKEN]", text)
        text = re.sub(r"(?i)\b(api[_ -]?key|secret|password|token)(\s*[:=]\s*)[^\s,;]+",
                      r"\1\2[REDACTED]", text)
        text = re.sub(r"\b(?:\d[ -]?){12,18}\d\b", "[LONG NUMBER]", text)
        return text

    def redact_value(self, value):
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self.redact_value(item) for key, item in value.items()}
        return value

