"""Create, check and revoke scoped business consent."""

from __future__ import annotations



def create_consent(seller_id: int, granted_by_user_id: int, purpose: str) -> int:
    """Reserved interface for a later implementation stage."""
    raise NotImplementedError("Not implemented in Stage 0")


def check_consent(seller_id: int, purpose: str, data_types: list[str]) -> bool:
    """Check current consent scope without granting implicit permission."""
    raise NotImplementedError("Not implemented in Stage 0")


def revoke_consent(seller_id: int, artifact_id: int) -> None:
    """Revoke an existing scoped consent artifact."""
    raise NotImplementedError("Not implemented in Stage 0")
