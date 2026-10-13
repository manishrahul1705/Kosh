"""Verify or export the Kosh audit chain."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from sqlalchemy import select
from app.audit.verify import verify_chain
from app.database.kosh_models import KoshAuditEntry
from app.database.session import get_session_factory
parser=argparse.ArgumentParser();parser.add_argument("--export-jsonl",type=Path);args=parser.parse_args()
with get_session_factory()() as db:
    result=verify_chain(db);print(f"VALID, {result.entries} entries" if result.valid else f"BROKEN at #{result.broken_at_sequence}: {result.reason}")
    if args.export_jsonl:
        args.export_jsonl.parent.mkdir(parents=True,exist_ok=True)
        with args.export_jsonl.open("w",encoding="utf-8",newline="\n") as out:
            for row in db.scalars(select(KoshAuditEntry).order_by(KoshAuditEntry.sequence)):
                out.write(json.dumps({c.name:getattr(row,c.name) for c in row.__table__.columns},default=str,sort_keys=True)+"\n")
