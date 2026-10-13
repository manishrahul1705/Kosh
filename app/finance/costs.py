"""Compare effective annual financing costs using integer-paise inputs."""

from __future__ import annotations

from decimal import Decimal


def effective_annual_cost(principal_paise: int, repayment_paise: int, days: int) -> Decimal:
    """Reserved interface for a later implementation stage."""
    raise NotImplementedError("Not implemented in Stage 0")
