"""Adapt financing criteria to existing eligibility statuses and reasons."""

from __future__ import annotations

from app.eligibility.constants import EligibilityStatus


def evaluate_product(seller_id: int, product_id: str) -> EligibilityStatus:
    """Reserved interface for a later implementation stage."""
    raise NotImplementedError("Not implemented in Stage 0")
