"""Structured logging: `event key=value ...` lines (text) or JSON lines."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_CONFIGURED = False


class _KeyValueFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%d %H:%M:%S")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", None) or record.getMessage(),
        }
        data.update(getattr(record, "fields", {}) or {})
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level.upper())
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if fmt == "json" else _KeyValueFormatter())
    root.handlers = [handler]
    # Keep third-party noise down.
    for noisy in ("httpx", "httpcore", "apscheduler.executors.default", "alembic.runtime.migration",
                  "alembic.runtime.plugins"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def _fmt_value(value: Any) -> str:
    text = str(value)
    if any(c.isspace() for c in text) or text == "":
        return json.dumps(text)
    return text


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Log `event k=v k=v`; JSON formatter receives the fields separately."""
    if not logger.isEnabledFor(level):
        return
    suffix = " ".join(f"{k}={_fmt_value(v)}" for k, v in fields.items())
    msg = f"{event} {suffix}".rstrip()
    logger.log(level, msg, extra={"event": event, "fields": fields})
