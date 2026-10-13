"""Stage 4 eligibility API with seller-scoped authorization."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import get_db
from app.api.seller_authorization import (
    EDIT_ROLES,
    READ_ROLES,
    authorize_seller,
    resolve_app_user,
)
from app.core.supabase_auth import AuthenticatedIdentity
from app.database.auth_models import SellerMembership
from app.database.models import EligibilityRun
from app.eligibility.service import EligibilityService
from app.schemas.eligibility import EligibilityEvaluationIn, EligibilityRunOut


router = APIRouter(prefix="/api/eligibility", tags=["eligibility"])


@router.post("/evaluate", response_model=EligibilityRunOut)
def evaluate_eligibility(
    payload: EligibilityEvaluationIn,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
):
    """Evaluate one seller against one tender with edit permission."""
    authorize_seller(payload.seller_id, identity, db, EDIT_ROLES)
    try:
        return EligibilityService(db).evaluate_tender(
            payload.tender_id,
            payload.seller_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[EligibilityRunOut])
def list_eligibility_runs(
    tender_id: int | None = Query(None),
    seller_id: int | None = Query(None),
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
):
    """List runs only for sellers with active read membership."""
    user = resolve_app_user(identity, db)

    if seller_id is not None:
        authorize_seller(seller_id, identity, db, READ_ROLES)

    permitted_sellers = (
        select(SellerMembership.seller_id)
        .where(
            SellerMembership.user_id == user.id,
            SellerMembership.status == "ACTIVE",
            SellerMembership.role.in_(READ_ROLES),
        )
    )

    stmt = select(EligibilityRun).where(
        EligibilityRun.seller_id.in_(permitted_sellers)
    )

    if tender_id is not None:
        stmt = stmt.where(EligibilityRun.tender_id == tender_id)

    if seller_id is not None:
        stmt = stmt.where(EligibilityRun.seller_id == seller_id)

    stmt = stmt.order_by(
        EligibilityRun.evaluated_at.desc(),
        EligibilityRun.id.desc(),
    )
    return list(db.scalars(stmt).all())


@router.get("/{run_id}", response_model=EligibilityRunOut)
def get_eligibility_run(
    run_id: int,
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
):
    """Return a run only when its seller is accessible."""
    run = db.get(EligibilityRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=f"Eligibility run {run_id} not found",
        )

    authorize_seller(run.seller_id, identity, db, READ_ROLES)
    return run
