"""Private seller-scoped document upload, processing and download."""
from pathlib import Path
import json
from fastapi import APIRouter,Depends,File,Form,HTTPException,Request,UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_edit,require_seller_read
from app.database.kosh_models import KoshPrivateDocument,KoshPrivateDocumentVersion
from app.documents.formats import DocumentFormatError
from app.finance.intake.private_store import resolve_private_path,store_private_document
from app.finance.intake.service import process_private_document

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/documents",tags=["kosh-documents"])

def _row(document,version=None):
    return {"id":document.id,"seller_id":document.seller_id,"kind":document.kind,"original_filename":document.original_filename,"status":document.status,"status_reason":document.status_reason,"current_version_id":document.current_version_id,"detected_format":getattr(version,"detected_format",None),"size_bytes":getattr(version,"size_bytes",None)}

@router.get("")
def list_business_documents(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    docs=db.scalars(select(KoshPrivateDocument).where(KoshPrivateDocument.seller_id==seller_id).order_by(KoshPrivateDocument.id.desc())).all()
    versions={v.id:v for v in db.scalars(select(KoshPrivateDocumentVersion).where(KoshPrivateDocumentVersion.seller_id==seller_id))}
    return [_row(d,versions.get(d.current_version_id)) for d in docs]

@router.get("/{document_id}")
def detail(seller_id:int,document_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    doc=db.scalar(select(KoshPrivateDocument).where(KoshPrivateDocument.id==document_id,KoshPrivateDocument.seller_id==seller_id))
    if not doc:raise HTTPException(404,"Document not found")
    return _row(doc,db.get(KoshPrivateDocumentVersion,doc.current_version_id))

@router.post("")
async def upload_business_document(request:Request,seller_id:int,kind:str=Form(...),file:UploadFile=File(...),db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    settings=request.app.state.settings;limit=settings.kosh_max_upload_mb*1024*1024
    content=await file.read(limit+1)
    try:doc,version,reused=store_private_document(db,seller_id=seller_id,user_id=access.user_id,kind=kind,filename=file.filename or "upload",content=content,storage_root=Path(settings.kosh_private_storage_path),max_bytes=limit)
    except PermissionError as exc:raise HTTPException(403,detail="CONSENT_REQUIRED") from exc
    except OverflowError as exc:raise HTTPException(413,detail="UPLOAD_TOO_LARGE") from exc
    except (DocumentFormatError,ValueError) as exc:raise HTTPException(422,detail=str(exc)) from exc
    result=_row(doc,version);result["reused_version"]=reused;return result

@router.get("/{document_id}/download")
def download(request:Request,seller_id:int,document_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    doc=db.scalar(select(KoshPrivateDocument).where(KoshPrivateDocument.id==document_id,KoshPrivateDocument.seller_id==seller_id))
    if not doc:raise HTTPException(404,"Document not found")
    version=db.get(KoshPrivateDocumentVersion,doc.current_version_id);path=resolve_private_path(Path(request.app.state.settings.kosh_private_storage_path),version)
    return FileResponse(path,filename=doc.original_filename,media_type="application/octet-stream",headers={"X-Content-Type-Options":"nosniff"})

@router.post("/{document_id}/process")
def process(request:Request,seller_id:int,document_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    doc=db.scalar(select(KoshPrivateDocument).where(KoshPrivateDocument.id==document_id,KoshPrivateDocument.seller_id==seller_id))
    if not doc:raise HTTPException(404,"Document not found")
    if doc.status in {"PROCESSED","REVIEW"}:return {"document_id":doc.id,"status":doc.status,"reason":doc.status_reason,"idempotent":True}
    version=db.get(KoshPrivateDocumentVersion,doc.current_version_id);path=resolve_private_path(Path(request.app.state.settings.kosh_private_storage_path),version)
    try:
        summary=process_private_document(db,document=doc,version=version,path=path,actor_id=access.user_id)
        return {"document_id":doc.id,"status":doc.status,"reason":doc.status_reason,**summary}
    except Exception as exc:
        db.rollback()
        failed=db.scalar(select(KoshPrivateDocument).where(KoshPrivateDocument.id==document_id,KoshPrivateDocument.seller_id==seller_id))
        if failed:
            failed.status="FAILED";failed.status_reason=f"PROCESSING_FAILED: {type(exc).__name__}";db.commit()
        raise HTTPException(422,detail=f"PROCESSING_FAILED: {type(exc).__name__}") from exc
