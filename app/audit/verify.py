"""Verify ordered audit entries and their hash chain."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence


def verify_chain(entries: Sequence[Mapping[str, object]]) -> bool:
    """Reserved interface for a later implementation stage."""
    raise NotImplementedError("Not implemented in Stage 0")
