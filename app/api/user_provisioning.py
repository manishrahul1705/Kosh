"""Authenticated application-user provisioning endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import get_db
from app.api.seller_authorization import provision_app_user
from app.core.supabase_auth import AuthenticatedIdentity

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/provision")
def provision_current_user(
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> dict:
    """Create or retrieve the application user for a verified identity."""
    user = provision_app_user(identity, db)
    db.commit()

    return {
        "user_id": user.id,
        "provisioned": True,
    }
