"""Optional raw-response snapshots for debugging (SAVE_DEBUG_SNAPSHOTS)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.collectors.gem_parser import redact_secrets

logger = logging.getLogger("app.collectors.debug")

_MAX_BYTES = 2_000_000


def save_debug_snapshot(settings, label: str, content: str | bytes) -> str | None:
    """Write a redacted snapshot under DEBUG_DIR when enabled. Returns the path."""
    if settings is None or not getattr(settings, "save_debug_snapshots", False):
        return None
    try:
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        content = redact_secrets(content)[:_MAX_BYTES]
        directory = settings.resolve_path(settings.debug_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", label)[:80]
        path = directory / f"{stamp}_{safe}.txt"
        path.write_text(content, encoding="utf-8")
        logger.info("debug_snapshot_saved path=%s", path)
        return str(path)
    except Exception:  # never let debugging break a run
        logger.warning("debug_snapshot_failed label=%s", label, exc_info=True)
        return None
