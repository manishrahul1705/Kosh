"""Load financing products and their criteria."""

from __future__ import annotations

from pathlib import Path


def load_products(path: Path) -> list[dict[str, object]]:
    """Reserved interface for a later implementation stage."""
    raise NotImplementedError("Not implemented in Stage 0")
