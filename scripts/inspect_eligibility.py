"""Stage 4: Eligibility Run Inspector.

Run eligibility evaluations and inspect historical runs.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import json
from typing import Optional, List, Dict, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    Tender,
    Seller,
    EligibilityRun,
    EligibilityRequirementResult,
    EligibilityEvidence
)
from app.database.session import build_engine, build_session_factory
from app.core.config import get_settings
from app.eligibility.service import EligibilityService
from app.utils.bid_number import normalize_bid_number


def run_evaluation(db: Session, bid_number: str, seller_id: int) -> Dict[str, Any]:
    """Run a new eligibility evaluation."""
    normalized_bid = normalize_bid_number(bid_number)
    tender = db.query(Tender).filter(Tender.bid_number == normalized_bid).first()
    if not tender:
        raise ValueError(f"Tender {bid_number} not found")

    service = EligibilityService(db)
    run = service.evaluate_tender(tender.id, seller_id)
    return get_run_details(db, run.id)


def get_run_details(db: Session, run_id: int) -> Dict[str, Any]:
    """Get detailed eligibility run information."""
    run = db.get(EligibilityRun, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    tender = db.get(Tender, run.tender_id)
    seller = db.get(Seller, run.seller_id)

    result = {
        "id": run.id,
        "tender_id": run.tender_id,
        "bid_number": tender.bid_number if tender else None,
        "seller_id": run.seller_id,
        "seller_name": seller.name if seller else None,
        "seller_revision_id": run.seller_revision_id,
        "corpus_fingerprint": run.corpus_fingerprint,
        "status": run.status,
        "summary": run.summary,
        "evaluated_at": run.evaluated_at.isoformat(),
        "stats": {
            "passed": run.passed_count,
            "failed": run.failed_count,
            "review": run.review_count,
            "insufficient": run.insufficient_count
        },
        "requirement_results": []
    }

    for res in run.results:
        res_data = {
            "id": res.id,
            "name": res.requirement_name,
            "type": res.requirement_type,
            "status": res.status,
            "reason": res.reason,
            "relaxation": res.relaxation_applied,
            "evidence": []
        }

        for ev in res.evidence:
            ev_data = {
                "attribute_id": ev.seller_attribute_id,
                "document_id": ev.seller_document_id,
                "value": ev.evidence_value
            }
            res_data["evidence"].append(ev_data)

        result["requirement_results"].append(res_data)

    return result


def main():
    parser = argparse.ArgumentParser(description="Inspect eligibility evaluations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Run evaluation
    run_parser = subparsers.add_parser("run", help="Run a new evaluation")
    run_parser.add_argument("--bid", required=True, help="Bid number")
    run_parser.add_argument("--seller-id", required=True, type=int, help="Seller ID")

    # Get run details
    get_parser = subparsers.add_parser("get", help="Get run details")
    get_parser.add_argument("run_id", type=int, help="Run ID")

    # List runs
    list_parser = subparsers.add_parser("list", help="List runs")
    list_parser.add_argument("--bid", help="Filter by bid number")
    list_parser.add_argument("--seller-id", type=int, help="Filter by seller ID")

    args = parser.parse_args()

    settings = get_settings()
    engine = build_engine(settings.resolved_database_url)
    session_factory = build_session_factory(engine)

    with session_factory() as db:
        try:
            if args.command == "run":
                result = run_evaluation(db, args.bid, args.seller_id)
                print(json.dumps(result, indent=2))
            elif args.command == "get":
                result = get_run_details(db, args.run_id)
                print(json.dumps(result, indent=2))
            elif args.command == "list":
                query = db.query(EligibilityRun)
                if args.bid:
                    normalized_bid = normalize_bid_number(args.bid)
                    query = query.join(Tender).filter(Tender.bid_number == normalized_bid)
                if args.seller_id:
                    query = query.filter(EligibilityRun.seller_id == args.seller_id)

                query = query.join(Seller, EligibilityRun.seller_id == Seller.id)
                query = query.add_columns(Tender.bid_number, Seller.name)

                runs = query.order_by(EligibilityRun.evaluated_at.desc()).all()
                result = []
                for r, bid_number, seller_name in runs:
                    result.append({
                        "id": r.id,
                        "bid": bid_number,
                        "seller": seller_name,
                        "status": r.status,
                        "evaluated_at": r.evaluated_at.isoformat()
                    })
                print(json.dumps(result, indent=2))
        except ValueError as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
