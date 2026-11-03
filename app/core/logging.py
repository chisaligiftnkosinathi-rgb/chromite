"""Application logging with secret redaction.

Every log record passes through ``RedactingFilter`` so that bearer tokens,
Supabase keys and JWTs are masked even if code accidentally logs them.
"""

import logging
import re

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"sb_(secret|publishable)_[A-Za-z0-9_-]+"), r"sb_\1_[REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "[REDACTED_JWT]"),
    (re.compile(r"(postgres(?:ql)?://[^:/\s]+:)[^@\s]+@"), r"\1[REDACTED]@"),
)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


_FORMATTER = logging.Formatter()


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed log call
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        # Tracebacks can contain secrets in exception messages.
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(_FORMATTER.formatException(record.exc_info))
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once; safe to call repeatedly."""
    global _CONFIGURED

    root = logging.getLogger()
    root.setLevel(level)

    if _CONFIGURED:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)

    # Also protect handlers added by uvicorn and others.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx"):
        logging.getLogger(name).addFilter(RedactingFilter())

    _CONFIGURED = True
