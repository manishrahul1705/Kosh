"""Read-authorized empty endpoints for future Kosh business workflows."""

from fastapi import APIRouter, Depends

from app.api.seller_authorization import AuthorizedSeller, require_seller_read
from app.schemas.kosh import (
    LedgerResponse, ForecastResponse, AlertsResponse,
    PlanResponse, ApprovalsResponse, AuditResponse,
)

router = APIRouter(prefix="/api/kosh/sellers/{seller_id}", tags=["kosh"])


@router.get("/ledger", response_model=LedgerResponse)
def get_ledger(
    seller_id: int,
    access: AuthorizedSeller = Depends(require_seller_read),
) -> LedgerResponse:
    """Return an explicit empty Stage 0 placeholder after authorization."""
    return LedgerResponse(seller_id=access.seller_id)


@router.get("/forecast/latest", response_model=ForecastResponse)
def get_latest_forecast(
    seller_id: int,
    access: AuthorizedSeller = Depends(require_seller_read),
) -> ForecastResponse:
    """Return an explicit empty Stage 0 placeholder after authorization."""
    return ForecastResponse(seller_id=access.seller_id)


@router.get("/alerts", response_model=AlertsResponse)
def get_alerts(
    seller_id: int,
    access: AuthorizedSeller = Depends(require_seller_read),
) -> AlertsResponse:
    """Return an explicit empty Stage 0 placeholder after authorization."""
    return AlertsResponse(seller_id=access.seller_id)


@router.get("/plan", response_model=PlanResponse)
def get_plan(
    seller_id: int,
    access: AuthorizedSeller = Depends(require_seller_read),
) -> PlanResponse:
    """Return an explicit empty Stage 0 placeholder after authorization."""
    return PlanResponse(seller_id=access.seller_id)


@router.get("/approvals", response_model=ApprovalsResponse)
def get_approvals(
    seller_id: int,
    access: AuthorizedSeller = Depends(require_seller_read),
) -> ApprovalsResponse:
    """Return an explicit empty Stage 0 placeholder after authorization."""
    return ApprovalsResponse(seller_id=access.seller_id)


@router.get("/audit", response_model=AuditResponse)
def get_audit(
    seller_id: int,
    access: AuthorizedSeller = Depends(require_seller_read),
) -> AuditResponse:
    """Return an explicit empty Stage 0 placeholder after authorization."""
    return AuditResponse(seller_id=access.seller_id)
