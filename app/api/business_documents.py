"""Private seller-scoped document placeholders; upload is not implemented."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.seller_authorization import (
    AuthorizedSeller,
    require_seller_edit,
    require_seller_read,
)
from app.schemas.kosh import BusinessDocumentPlaceholder

router = APIRouter(prefix="/api/kosh/sellers/{seller_id}/documents", tags=["kosh-documents"])


@router.get("", response_model=list[BusinessDocumentPlaceholder])
def list_business_documents(
    seller_id: int,
    access: AuthorizedSeller = Depends(require_seller_read),
) -> list[BusinessDocumentPlaceholder]:
    """List no documents until private storage is implemented."""
    return []


@router.post("", status_code=501)
def upload_business_document(
    seller_id: int,
    access: AuthorizedSeller = Depends(require_seller_edit),
) -> None:
    """Authorize edits before reporting the unavailable upload operation."""
    raise HTTPException(status_code=501, detail="Private document upload is not implemented in Stage 0")
