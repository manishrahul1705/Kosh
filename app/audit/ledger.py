"""Append a canonical event to the audit hash chain."""

from __future__ import annotations

from collections.abc import Mapping


def append_entry(seller_id: int | None, payload: Mapping[str, object]) -> str:
    """Reserved interface for a later implementation stage."""
    raise NotImplementedError("Not implemented in Stage 0")
