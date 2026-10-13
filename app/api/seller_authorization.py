"""Database-backed seller authorization."""

from dataclasses import dataclass

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import get_db
from app.core.supabase_auth import AuthenticatedIdentity
from app.database.auth_models import AppUser, SellerMembership


READ_ROLES = frozenset({
    "OWNER", "ADMIN", "EDITOR", "VIEWER", "APPROVER"
})

EDIT_ROLES = frozenset({
    "OWNER", "ADMIN", "EDITOR"
})

APPROVE_ROLES = frozenset({
    "OWNER", "APPROVER"
})


@dataclass(frozen=True)
class AuthorizedSeller:
    user_id: int
    seller_id: int
    role: str



def provision_app_user(
    identity: AuthenticatedIdentity,
    db: Session,
) -> AppUser:
    """Provision a verified Supabase identity without seller privileges."""
    from sqlalchemy.exc import IntegrityError

    subject = identity.subject

    if not subject:
        raise HTTPException(
            status_code=401,
            detail="Invalid authenticated identity",
        )

    existing = (
        db.query(AppUser)
        .filter(AppUser.supabase_user_id == subject)
        .one_or_none()
    )

    if existing is not None:
        return existing

    try:
        with db.begin_nested():
            db.add(AppUser(supabase_user_id=subject))
            db.flush()
    except IntegrityError:
        # Concurrent first-login requests may create the same user.
        pass

    user = (
        db.query(AppUser)
        .filter(AppUser.supabase_user_id == subject)
        .one_or_none()
    )

    if user is None:
        raise HTTPException(
            status_code=500,
            detail="Application user provisioning failed",
        )

    return user


def resolve_app_user(
    identity: AuthenticatedIdentity,
    db: Session,
) -> AppUser:
    user = (
        db.query(AppUser)
        .filter(
            AppUser.supabase_user_id == identity.subject
        )
        .one_or_none()
    )

    if user is None:
        raise HTTPException(
            status_code=403,
            detail="Application user is not provisioned",
        )

    return user


def authorize_seller(
    seller_id: int,
    identity: AuthenticatedIdentity,
    db: Session,
    allowed_roles: frozenset[str],
) -> AuthorizedSeller:
    user = resolve_app_user(identity, db)

    membership = (
        db.query(SellerMembership)
        .filter(
            SellerMembership.user_id == user.id,
            SellerMembership.seller_id == seller_id,
            SellerMembership.status == "ACTIVE",
        )
        .one_or_none()
    )

    if membership is None or membership.role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail="Seller access denied",
        )

    return AuthorizedSeller(
        user_id=user.id,
        seller_id=seller_id,
        role=membership.role,
    )


def require_seller_read(
    seller_id: int,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> AuthorizedSeller:
    return authorize_seller(
        seller_id, identity, db, READ_ROLES
    )


def require_seller_edit(
    seller_id: int,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> AuthorizedSeller:
    return authorize_seller(
        seller_id, identity, db, EDIT_ROLES
    )


def require_seller_approval(
    seller_id: int,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> AuthorizedSeller:
    return authorize_seller(
        seller_id, identity, db, APPROVE_ROLES
    )
