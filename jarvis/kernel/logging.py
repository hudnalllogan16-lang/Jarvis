"""Structured logging with secret redaction.

Spec §10: secrets MUST NOT appear in code, logs, or prompts. Redaction here is a
backstop, not the primary control — the primary control is that secrets are held
as `SecretStr` and resolved only at the tool-execution boundary (D-002 note).
Defence in depth is appropriate for a rule the spec states absolutely.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any, Final, cast

_SECRET_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|credential|authorization|bearer|dsn|url)",
    re.IGNORECASE,
)

_SECRET_VALUE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b[a-z+]+://[^:\s]+:[^@\s]+@\S+\b"),
)

REDACTED: Final[str] = "[REDACTED]"


def redact(value: Any) -> Any:
    """Recursively redact probable secret material from a log payload.

    Args:
        value: Any JSON-ish structure destined for a log record.

    Returns:
        The same structure with secret-looking keys and values replaced by
        ``[REDACTED]``. Non-JSON values are returned unchanged.
    """
    if isinstance(value, dict):
        mapping = cast("dict[str, Any]", value)
        return {
            k: (REDACTED if _SECRET_KEY_PATTERN.search(str(k)) else redact(v))
            for k, v in mapping.items()
        }
    if isinstance(value, (list, tuple)):
        sequence = cast("list[Any] | tuple[Any, ...]", value)
        return [redact(v) for v in sequence]
    if isinstance(value, str):
        out = value
        for pattern in _SECRET_VALUE_PATTERNS:
            out = pattern.sub(REDACTED, out)
        return out
    return value


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record, with secrets redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload["context"] = redact(context)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger. Idempotent.

    Args:
        level: Logging level name, already validated by `Settings`.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for existing in list(root.handlers):
        root.removeHandler(existing)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger.

    Args:
        name: Conventionally ``__name__``.
    """
    return logging.getLogger(name)
