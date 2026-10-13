"""Stage 4: Eligibility Service Layer.

Loads tender facts, seller revision, invokes the engine,
calculates readiness, and persists eligibility runs.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import json

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database.models import (
    Tender,
    TenderFieldValue,
    AIRequirement,
    AIRequirementEvidence,
    Seller,
    SellerRevision,
    SellerAttribute,
    SellerDocument,
    EligibilityRun,
    EligibilityRequirementResult,
    EligibilityEvidence,
    AIAnalysisRun,
    AIAnalysisFlag
)
from app.corpus.service import build_corpus
from app.eligibility.engine import EligibilityEngine
from app.eligibility.constants import EligibilityStatus, RequirementStatus
from app.eligibility.utils import calculate_seller_fingerprint
from app.eligibility.ai_state_fingerprint import calculate_ai_state_fingerprint

class EligibilityService:
    """Service layer for evaluating seller eligibility against tenders."""

    def __init__(self, db: Session):
        self.db = db
        self.engine = EligibilityEngine()

    def evaluate_tender(self, tender_id: int, seller_id: int) -> EligibilityRun:
        """Run eligibility evaluation for a tender and seller.

        Args:
            tender_id: ID of the tender.
            seller_id: ID of the seller.

        Returns:
            Saved EligibilityRun instance.
        """
        from app.database.session import reserve_sqlite_writer
        reserve_sqlite_writer(self.db, renew_read=True)
        # 1. Fetch Tender & Corpus
        tender = self.db.get(Tender, tender_id)
        if not tender:
            raise ValueError(f"Tender {tender_id} not found.")

        corpus_data = build_corpus(self.db, tender_id)
        corpus_fingerprint = corpus_data["fingerprint"]
        corpus_complete = corpus_data["completeness"] == "COMPLETE"

        # 2. Fetch Active Seller Revision
        seller = self.db.get(Seller, seller_id)
        if not seller:
            raise ValueError(f"Seller {seller_id} not found.")

        stmt = select(SellerRevision).where(
            SellerRevision.seller_id == seller_id,
            SellerRevision.is_active == True
        ).order_by(SellerRevision.revision_number.desc())

        seller_revision = self.db.scalars(stmt).first()
        if not seller_revision:
            raise ValueError(f"No active revision found for seller {seller_id}.")

        from app.corpus.analysis import CORPUS_PROMPT_VERSION
        # Snapshot the current Stage 3C corpus analysis before idempotency lookup.
        ai_run = self.db.scalars(
            select(AIAnalysisRun).where(
                AIAnalysisRun.tender_id == tender_id,
                AIAnalysisRun.analysis_scope == "TENDER_CORPUS",
                AIAnalysisRun.is_current == True,
                AIAnalysisRun.corpus_fingerprint == corpus_data["fingerprint"],
                AIAnalysisRun.prompt_version == CORPUS_PROMPT_VERSION
            ).order_by(AIAnalysisRun.id.desc())
        ).first()
        ai_analysis_run_id = ai_run.id if ai_run else None
        ai_state_fingerprint = calculate_ai_state_fingerprint(self.db, ai_run)

        # Reuse only the exact corpus, seller revision, engine, and AI state.
        existing_run = self.db.scalar(
            select(EligibilityRun).where(
                EligibilityRun.tender_id == tender_id,
                EligibilityRun.seller_revision_id == seller_revision.id,
                EligibilityRun.corpus_fingerprint == corpus_fingerprint,
                EligibilityRun.engine_version == self.engine.engine_version,
                EligibilityRun.ai_state_fingerprint == ai_state_fingerprint
            )
        )

        if existing_run:
            return existing_run

        # 3. Build Seller Profile Payload
        seller_profile = self._build_seller_profile_payload(seller_revision)

        # 4. Extract Requirements from Stage 3B and Stage 3C
        requirements, ai_analysis_run_id = self._extract_tender_requirements(tender_id, corpus_data, ai_run)

        # 5. Evaluate each requirement
        results = []
        passed = 0
        failed = 0
        review = 0
        insufficient = 0

        for req in requirements:
            eval_res = self.engine.evaluate_requirement(req, seller_profile)
            results.append((req, eval_res))

            status = eval_res["status"]
            if status in (RequirementStatus.PASS.value, RequirementStatus.PASS_WITH_RELAXATION.value):
                passed += 1
            elif status == RequirementStatus.FAIL.value:
                failed += 1
            elif status == RequirementStatus.REVIEW_REQUIRED.value:
                review += 1
            elif status == RequirementStatus.INSUFFICIENT_INFORMATION.value:
                insufficient += 1

        # 6. Overall Decision
        overall_status = self.engine.determine_overall_status(
            [r[1] for r in results],
            corpus_complete=corpus_complete
        )

        # Unresolved corpus conflicts must not result in automatic approval.
        # Preserve ANALYSIS_INCOMPLETE for an incomplete document corpus.
        if (
            corpus_complete
            and corpus_data.get("conflicts")
            and overall_status == EligibilityStatus.ELIGIBLE
        ):
            overall_status = EligibilityStatus.REVIEW_REQUIRED

        # Unresolved conflicts in mandatory AI requirements require human review.
        ai_review_reasons = []

        # Partial AI analysis cannot support automatic eligibility approval.
        # Preserve definitive failures and incomplete-corpus decisions.
        if (
            ai_run
            and ai_run.status == "PARTIAL_SUCCESS"
            and overall_status == EligibilityStatus.ELIGIBLE
        ):
            overall_status = EligibilityStatus.REVIEW_REQUIRED
            ai_review_reasons.append(
                "Stage 3C analysis is PARTIAL_SUCCESS; human review required"
            )

        if ai_run and overall_status == EligibilityStatus.ELIGIBLE:
            mandatory_ai_ids = {
                req["ai_requirement_id"]
                for req in requirements
                if req.get("ai_requirement_id") is not None
                and req.get("obligation") == "MANDATORY"
            }

            if mandatory_ai_ids:
                flags = self.db.scalars(
                    select(AIAnalysisFlag).where(
                        AIAnalysisFlag.analysis_run_id == ai_run.id,
                        AIAnalysisFlag.requirement_id.in_(mandatory_ai_ids),
                        AIAnalysisFlag.flag_type.in_((
                            "AI_DETERMINISTIC_CONFLICT",
                            "CONTRADICTORY_REQUIREMENT",
                            "AMBIGUOUS_ATC",
                            "REVIEW_REQUIRED",
                        )),
                    )
                ).all()

                if flags:
                    overall_status = EligibilityStatus.REVIEW_REQUIRED
                    ai_review_reasons = [
                        f"AI flag {flag.id}: {flag.flag_type}"
                        for flag in flags
                    ]
        # 7. Persist Run
        run = EligibilityRun(
            tender_id=tender_id,
            seller_id=seller_id,
            seller_revision_id=seller_revision.id,
            ai_analysis_run_id=ai_analysis_run_id,
            ai_state_fingerprint=ai_state_fingerprint,
            corpus_fingerprint=corpus_fingerprint,
            engine_version=self.engine.engine_version,
            status=overall_status.value,
            summary=f"Evaluation complete. Passed: {passed}, Failed: {failed}, Review: {review}, Insufficient: {insufficient}. AI review: {'; '.join(ai_review_reasons) if ai_review_reasons else 'none'}",
            passed_count=passed,
            failed_count=failed,
            review_count=review,
            insufficient_count=insufficient,
            evaluated_at=datetime.utcnow()
        )
        self.db.add(run)
        self.db.flush() # Get ID

        # 8. Persist Requirement Results & Evidence
        for req, eval_res in results:
            res_row = EligibilityRequirementResult(
                run_id=run.id,
                requirement_name=eval_res["requirement_name"],
                requirement_type=eval_res["requirement_type"],
                status=eval_res["status"],
                reason=eval_res["reason"],
                relaxation_applied=eval_res.get("relaxation_applied"),
                stage3b_field_id=req.get("stage3b_field_id"),
                ai_requirement_id=req.get("ai_requirement_id")
            )
            self.db.add(res_row)
            self.db.flush()

            # Attach evidence links if any
            for attr_id in eval_res.get("seller_attribute_ids", []):
                self.db.add(EligibilityEvidence(
                    result_id=res_row.id,
                    seller_attribute_id=attr_id
                ))
            for doc_id in eval_res.get("seller_document_ids", []):
                self.db.add(EligibilityEvidence(
                    result_id=res_row.id,
                    seller_document_id=doc_id
                ))

        self.db.commit()
        return run

    def _build_seller_profile_payload(self, revision: SellerRevision) -> Dict[str, Any]:
        """Convert Revision DB models to engine-compatible dictionary."""
        attrs = []
        for a in revision.attributes:
            attrs.append({
                "id": a.id,
                "key": a.key,
                "value_type": a.value_type,
                "value_text": a.value_text,
                "value_number": a.value_number,
                "value_json": a.value_json
            })

        docs = []
        for d in revision.documents:
            docs.append({
                "id": d.id,
                "document_type": d.document_type,
                "filename": d.filename,
                "issue_date": d.issue_date,
                "expiry_date": d.expiry_date,
                "status": d.status
            })

        return {
            "attributes": attrs,
            "documents": docs
        }

    def _extract_tender_requirements(self, tender_id: int, corpus_data: Dict[str, Any], ai_run: Optional[AIAnalysisRun] = None) -> List[Dict[str, Any]]:
        """Collect all structured requirements from Stage 3B and 3C for this tender."""
        requirements = []
        relaxation_fields = {}
        relaxation_candidates = {}

        # First pass: Collect all relaxation fields
        for doc_entry in corpus_data.get("documents", []):
            field_ext = doc_entry.get("stage3b_extraction_id")
            if not field_ext:
                continue

            stmt = select(TenderFieldValue).where(TenderFieldValue.field_extraction_id == field_ext)
            field_values = self.db.scalars(stmt).all()

            for fv in field_values:
                if "relaxation" in fv.field_name or fv.field_name == "emd_exemption_allowed":
                    if fv.status == "CONFLICT":
                        relaxation_candidates.setdefault(fv.field_name, set()).update({True, False})
                    elif fv.status == "RESOLVED" and fv.tri_state in ("TRUE", "FALSE"):
                        relaxation_candidates.setdefault(fv.field_name, set()).add(fv.tri_state == "TRUE")

        relaxation_fields = {name: next(iter(values)) if len(values) == 1 else None
                             for name, values in relaxation_candidates.items()}

        # The registry's combined fields cover both criteria. Conflicting source
        # values must not silently enable or disable a statutory relaxation.
        for entity in ("mse", "startup"):
            combined_name = f"{entity}_experience_turnover_relaxation"
            combined = relaxation_fields.get(combined_name)
            if combined_name in relaxation_fields:
                for criterion in ("experience", "turnover"):
                    relaxation_fields.setdefault(f"{entity}_{criterion}_relaxation", combined)

        # Second pass: Collect requirements and attach relaxation flags
        for doc_entry in corpus_data.get("documents", []):
            field_ext = doc_entry.get("stage3b_extraction_id")
            if not field_ext:
                continue

            stmt = select(TenderFieldValue).where(TenderFieldValue.field_extraction_id == field_ext)
            field_values = self.db.scalars(stmt).all()

            for fv in field_values:
                amount_field = fv.field_name in ("bidder_turnover_amount", "oem_turnover_amount")
                numeric_field = amount_field or fv.field_name == "experience_years"
                threshold_name = {"bidder_turnover_required": "bidder_turnover_amount",
                                  "oem_turnover_required": "oem_turnover_amount",
                                  "experience_required": "experience_years"}.get(fv.field_name)
                has_amount = any(
                    a.field_name == threshold_name
                    and a.status == "RESOLVED" for a in field_values
                ) if threshold_name else False
                if has_amount:
                    continue
                if fv.status == "RESOLVED" and (fv.tri_state in ("TRUE", "FALSE") or numeric_field):
                    req_type = self._map_field_name_to_type(fv.field_name)
                    if req_type == "RELAXATION":
                        continue

                    # Create requirement
                    requirement = {
                        "name": fv.field_name,
                        "title": fv.field_name.replace("_", " ").title(),
                        "type": req_type,
                        "value_boolean": None if numeric_field else fv.tri_state == "TRUE",
                        "value_number": fv.value_number,
                        "value_text": fv.value_text,
                        "obligation": "OPTIONAL" if fv.field_name in ("mse_purchase_preference", "mii_purchase_preference") else "MANDATORY",
                        "stage3b_field_id": fv.id
                    }
                    if amount_field:
                        requirement["applies_to"] = "OEM" if fv.field_name.startswith("oem_") else "BIDDER"
                    requirement["relaxation_conflict"] = any(v is None for v in relaxation_fields.values())

                    # Attach relaxation flags based on requirement type
                    if req_type == "EXPERIENCE":
                        if "startup_experience_relaxation" in relaxation_fields:
                            requirement["startup_relaxation"] = relaxation_fields["startup_experience_relaxation"]
                        if "mse_experience_relaxation" in relaxation_fields:
                            requirement["mse_relaxation"] = relaxation_fields["mse_experience_relaxation"]
                    elif req_type == "EMD":
                        if "emd_exemption_allowed" in relaxation_fields:
                            requirement["emd_exemption_allowed"] = relaxation_fields["emd_exemption_allowed"]
                    elif req_type == "TURNOVER":
                        if "startup_turnover_relaxation" in relaxation_fields:
                            requirement["startup_relaxation"] = relaxation_fields["startup_turnover_relaxation"]
                        if "mse_turnover_relaxation" in relaxation_fields:
                            requirement["mse_relaxation"] = relaxation_fields["mse_turnover_relaxation"]

                    requirements.append(requirement)

        # 2. Collect Stage 3C AI Requirements if available
        # Reuse the validated AI snapshot selected before cache lookup.
        if ai_run:
            ai_requirements = self.db.scalars(select(AIRequirement).where(AIRequirement.analysis_run_id == ai_run.id).order_by(AIRequirement.sequence.asc())).all()
            for req in ai_requirements:
                req_type = req.requirement_type
                requirement = {
                    "name": req.title,
                    "title": req.title,
                    "type": req_type,
                    "value_number": req.value_number,
                    "value_text": req.value_text,
                    "obligation": req.obligation_level,
                    "ai_requirement_id": req.id
                }
                requirement["relaxation_conflict"] = any(v is None for v in relaxation_fields.values())
                if req_type == "TURNOVER":
                    requirement["applies_to"] = req.applies_to
                    from app.fields.turnover import turnover_amount
                    quotes = self.db.scalars(select(AIRequirementEvidence.quote).where(
                        AIRequirementEvidence.requirement_id == req.id
                    )).all()
                    amount = turnover_amount("\n".join(quotes))
                    # Protect comparisons against historical AI rows too; no DB repair.
                    requirement["value_number"] = amount.number if amount else None

                # Set relaxation flags based on requirement type
                if req_type == "EXPERIENCE":
                    if "startup_experience_relaxation" in relaxation_fields:
                        requirement["startup_relaxation"] = relaxation_fields["startup_experience_relaxation"]
                    if "mse_experience_relaxation" in relaxation_fields:
                        requirement["mse_relaxation"] = relaxation_fields["mse_experience_relaxation"]
                elif req_type == "TURNOVER":
                    if "startup_turnover_relaxation" in relaxation_fields:
                        requirement["startup_relaxation"] = relaxation_fields["startup_turnover_relaxation"]
                    if "mse_turnover_relaxation" in relaxation_fields:
                        requirement["mse_relaxation"] = relaxation_fields["mse_turnover_relaxation"]

                requirements.append(requirement)

        # Equal structured obligations repeated across package documents are one
        # gate. Retain every source field ID; differing values remain separate
        # and existing corpus conflict handling prevents automatic approval.
        consolidated=[];seen={}
        for req in requirements:
            fid=req.get('stage3b_field_id')
            if not fid:
                consolidated.append(req);continue
            key=json.dumps({k:v for k,v in req.items() if k not in ('stage3b_field_id','title')},sort_keys=True,default=str)
            if key in seen:seen[key]['stage3b_field_ids'].append(fid)
            else:
                req['stage3b_field_ids']=[fid];seen[key]=req;consolidated.append(req)
        return consolidated, (ai_run.id if ai_run else None)

    def _map_field_name_to_type(self, field_name: str) -> str:
        """Map 3B field names to engine RequirementTypes."""
        if "relaxation" in field_name or field_name == "emd_exemption_allowed":
            return "RELAXATION"
        if "experience" in field_name:
            return "EXPERIENCE"
        if "turnover" in field_name:
            return "TURNOVER"
        if "oem" in field_name:
            return "OEM_AUTHORIZATION"
        if "iso" in field_name:
            return "ISO"
        if "mse" in field_name:
            return "MSE"
        if "startup" in field_name:
            return "STARTUP"
        if "emd" in field_name:
            return "EMD"
        if "epbg" in field_name:
            return "EPBG"
        return "OTHER"









