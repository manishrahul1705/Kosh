"""Validated immutable storage for seller-private documents."""
from pathlib import Path
import hashlib,json,os,tempfile
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.audit.ledger import append_event
from app.consent.service import get_active_consent
from app.database.kosh_models import KoshPrivateDocument,KoshPrivateDocumentVersion
from app.documents.formats import DocumentFormatError,inspect_document
from app.utils.dates import utcnow

KIND_DATA={"BANK_STATEMENT":"BANK_STATEMENT","SALES_INVOICE":"SALES_INVOICES","PURCHASE_BILL":"PURCHASE_BILLS","BOOKS_EXPORT":"BOOKS_EXPORT","OTHER":"BUSINESS_PROFILE"}
ALLOWED={"pdf","xlsx","csv","txt","json","png","jpg","jpeg"}

def _validate(path:Path,extension:str)->str:
    if extension=="json":
        try:
            value=json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(value,(dict,list)):raise ValueError
        except (ValueError,UnicodeError,json.JSONDecodeError) as exc:raise DocumentFormatError("INVALID_JSON") from exc
        return "json"
    return inspect_document(path,expected=extension)

def store_private_document(session:Session,*,seller_id:int,user_id:int,kind:str,filename:str,content:bytes,storage_root:Path,max_bytes:int)->tuple[KoshPrivateDocument,KoshPrivateDocumentVersion,bool]:
    if kind not in KIND_DATA:raise ValueError("INVALID_DOCUMENT_KIND")
    consent=get_active_consent(session,seller_id,KIND_DATA[kind])
    if consent is None:raise PermissionError("CONSENT_REQUIRED")
    if len(content)>max_bytes:raise OverflowError("UPLOAD_TOO_LARGE")
    extension=Path(filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED:raise DocumentFormatError("UNSUPPORTED_FORMAT")
    digest=hashlib.sha256(content).hexdigest();root=storage_root.resolve();root.mkdir(parents=True,exist_ok=True);target=(root/str(seller_id)/digest).resolve()
    target.relative_to(root)
    with tempfile.NamedTemporaryFile(dir=root,delete=False) as temp:
        temp.write(content);temp_path=Path(temp.name)
    try:detected=_validate(temp_path,extension)
    except Exception:temp_path.unlink(missing_ok=True);raise
    document=KoshPrivateDocument(seller_id=seller_id,kind=kind,original_filename=Path(filename).name[:255],uploaded_by_user_id=user_id,consent_id=consent.id,status="UPLOADED",created_at=utcnow(),updated_at=utcnow())
    session.add(document);session.flush()
    existing=session.scalar(select(KoshPrivateDocumentVersion).where(KoshPrivateDocumentVersion.seller_id==seller_id,KoshPrivateDocumentVersion.sha256==digest))
    reused=existing is not None
    if existing:version=existing;temp_path.unlink(missing_ok=True)
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        os.replace(temp_path,target)
        version=KoshPrivateDocumentVersion(document_id=document.id,seller_id=seller_id,sha256=digest,size_bytes=len(content),detected_format=detected,storage_key=f"{seller_id}/{digest}",created_at=utcnow());session.add(version);session.flush()
    document.current_version_id=version.id
    append_event(session,seller_id=seller_id,actor_type="HUMAN",actor_id=str(user_id),action="document.upload",tier="T1_DRAFT",payload={"document_id":document.id,"version_id":version.id,"kind":kind,"sha256":digest,"reused":reused},policy_decision="ALLOW")
    session.commit();return document,version,reused

def resolve_private_path(root:Path,version:KoshPrivateDocumentVersion)->Path:
    base=root.resolve();candidate=(base/version.storage_key).resolve();candidate.relative_to(base)
    if not candidate.is_file():raise FileNotFoundError("PRIVATE_FILE_MISSING")
    return candidate
