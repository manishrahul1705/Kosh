"""Read sandbox bank transactions without a live connection."""

from __future__ import annotations



def fetch_transactions(seller_id: int) -> list[dict[str, object]]:
    """Reserved interface for a later implementation stage."""
    raise NotImplementedError("Not implemented in Stage 0")
