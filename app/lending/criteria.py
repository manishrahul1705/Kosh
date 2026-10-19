"""Define and validate financing criterion types."""

from __future__ import annotations

from collections.abc import Mapping


def validate_criterion(criterion: Mapping[str, object]) -> dict[str, object]:
    """Reserved interface for a later implementation stage."""
    raise NotImplementedError("Not implemented in Stage 0")
