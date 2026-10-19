"""Issue and verify approval tokens for scoped actions."""

from __future__ import annotations



def issue_approval_token(seller_id: int, action: str, params_hash: str) -> str:
    """Reserved interface for a later implementation stage."""
    raise NotImplementedError("Not implemented in Stage 0")


def verify_approval_token(token: str, seller_id: int, action: str, params_hash: str) -> bool:
    """Verify scope and binding before a future approved action."""
    raise NotImplementedError("Not implemented in Stage 0")
