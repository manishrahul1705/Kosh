"""Deterministic fingerprint of AI state used by eligibility evaluation."""

import hashlib
import json

from sqlalchemy import select

from app.database.models import AIRequirement, AIAnalysisFlag


def calculate_ai_state_fingerprint(db, ai_run):
    """Hash decision-relevant AI state, including requirements and flags."""
    if ai_run is None:
        payload = {"schema": 1, "analysis": None}
    else:
        requirements = db.scalars(
            select(AIRequirement)
            .where(AIRequirement.analysis_run_id == ai_run.id)
            .order_by(AIRequirement.id)
        ).all()

        flags = db.scalars(
            select(AIAnalysisFlag)
            .where(AIAnalysisFlag.analysis_run_id == ai_run.id)
            .order_by(AIAnalysisFlag.id)
        ).all()

        requirement_fields = (
            "id", "sequence", "requirement_type", "model_requirement_type",
            "category", "title", "summary", "obligation", "obligation_level",
            "model_obligation_level", "level_adjustment", "condition_text",
            "value_text", "value_number", "unit", "applies_to",
            "risk_flags_json", "ambiguity", "is_buyer_atc",
        )

        flag_fields = (
            "id", "requirement_id", "flag_type", "severity", "message",
            "stage3b_field_name", "stage3b_value",
            "stage3b_evidence_strength", "ai_value", "chunk_keys_json",
        )

        payload = {
            "schema": 1,
            "analysis": {
                "id": ai_run.id,
                "status": ai_run.status,
                "status_code": ai_run.status_code,
                "corpus_fingerprint": ai_run.corpus_fingerprint,
                "corpus_completeness": ai_run.corpus_completeness,
                "requirements": [
                    {field: getattr(item, field) for field in requirement_fields}
                    for item in requirements
                ],
                "flags": [
                    {field: getattr(item, field) for field in flag_fields}
                    for item in flags
                ],
            },
        }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
