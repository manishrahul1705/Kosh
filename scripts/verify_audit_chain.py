"""Verify persisted audit integrity or a tenant-private JSONL export."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from sqlalchemy import select
from app.audit.verify import verify_chain
from app.audit.export import export_jsonl,verify_jsonl
from app.audit.ledger import canonical_json
from app.database.kosh_models import KoshAuditEntry
from app.database.session import get_session_factory

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--export-jsonl",type=Path)
    parser.add_argument("--verify-jsonl",type=Path)
    parser.add_argument("--seller-id",type=int)
    args=parser.parse_args()
    with get_session_factory()() as db:
        if args.verify_jsonl:
            if args.seller_id is None:parser.error("--seller-id is required to verify a scoped export")
            result=verify_jsonl(db,args.seller_id,args.verify_jsonl.read_text(encoding="utf-8-sig"))
            print(json.dumps(result,sort_keys=True));return 0 if result["valid"] else 1
        result=verify_chain(db)
        print(f"VALID, {result.entries} entries" if result.valid else f"BROKEN at #{result.broken_at_sequence}: {result.reason}")
        if args.export_jsonl:
            args.export_jsonl.parent.mkdir(parents=True,exist_ok=True)
            if args.seller_id is not None:text=export_jsonl(db,args.seller_id)
            else:text="\n".join(canonical_json({c.name:getattr(row,c.name) for c in row.__table__.columns}) for row in db.scalars(select(KoshAuditEntry).order_by(KoshAuditEntry.sequence)))+"\n"
            args.export_jsonl.write_text(text,encoding="utf-8")
        return 0 if result.valid else 1

if __name__=="__main__":raise SystemExit(main())
