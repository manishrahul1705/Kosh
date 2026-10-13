"""Stage 4: Eligibility Engine Core Logic.

Purely deterministic matching logic between Tender requirements
and Seller profile data.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from app.eligibility.constants import (
    RequirementStatus,
    RequirementType,
    RelaxationRule,
    EligibilityStatus,
    AttributeKey,
    DocumentType
)
from app.eligibility.utils import (
    get_seller_attribute_value,
    get_seller_document_by_type,
    is_document_valid
)


class EligibilityEngine:
    """Deterministic engine for comparing tender requirements against a seller profile."""

    def __init__(self, engine_version: str = "1.9.0"):  # Numeric obligations and missing exemption/reservation status.
        self.engine_version = engine_version

    def evaluate_requirement(
        self,
        requirement: Dict[str, Any],
        seller_profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate a single tender requirement against the seller profile.

        Args:
            requirement: Dict containing requirement type, value, obligation level, etc.
            seller_profile: Dict containing seller attributes and documents.

        Returns:
            Dict containing status, reason, relaxation used, and evidence.
        """
        req_type_str = requirement.get("type", "").upper()
        obligation = requirement.get("obligation", "MANDATORY").upper()

        # Default result
        result = {
            "requirement_name": requirement.get("title", requirement.get("name", "Unknown Requirement")),
            "requirement_type": req_type_str,
            "status": RequirementStatus.REVIEW_REQUIRED.value,
            "reason": "Unknown requirement type or complex criteria requiring manual review.",
            "relaxation_applied": None,
            "evidence": []
        }

        # Optional and informational criteria do not independently determine eligibility.
        if obligation in ("OPTIONAL", "INFORMATIONAL"):
            result["status"] = RequirementStatus.NOT_APPLICABLE.value
            result["reason"] = "Non-mandatory criterion; excluded from eligibility gating."
            return result
        if obligation != "MANDATORY":
            result["reason"] = "Obligation or applicability is unresolved; human review is required."
            return result
        if requirement.get("value_boolean") is False:
            result["status"] = RequirementStatus.NOT_APPLICABLE.value
            result["reason"] = "Tender explicitly states this requirement is not applicable."
            return result

        # Dispatch based on requirement type
        if req_type_str == RequirementType.EXPERIENCE.value:
            return self._evaluate_experience(requirement, seller_profile, result)
        elif req_type_str == RequirementType.TURNOVER.value:
            return self._evaluate_turnover(requirement, seller_profile, result)
        elif req_type_str == RequirementType.PAST_PERFORMANCE.value:
            return self._evaluate_past_performance(requirement, seller_profile, result)
        elif req_type_str == RequirementType.OEM_AUTHORIZATION.value:
            return self._evaluate_oem_auth(requirement, seller_profile, result)
        elif req_type_str == RequirementType.ISO.value:
            return self._evaluate_iso(requirement, seller_profile, result)
        elif req_type_str == RequirementType.MSE.value:
            return self._evaluate_mse(requirement, seller_profile, result)
        elif req_type_str == RequirementType.STARTUP.value:
            return self._evaluate_startup(requirement, seller_profile, result)
        elif req_type_str in (RequirementType.EMD.value, RequirementType.EPBG.value):
            return self._evaluate_exemptible_requirement(requirement, seller_profile, result)

        # If optional and not failed, it can be PASS
        if obligation in ("OPTIONAL", "INFORMATIONAL"):
            result["status"] = RequirementStatus.PASS.value
            result["reason"] = f"Optional requirement: {requirement.get('title')}"

        return result

    def _evaluate_experience(self, req: Dict[str, Any], seller: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:

        # Skip relaxation fields - they are not actual requirements
        if req.get("type") == "RELAXATION":
            result["status"] = RequirementStatus.NOT_APPLICABLE.value
            result["reason"] = "Relaxation field - not a requirement."
            return result

        req_years = req.get("value_number")
        seller_years = get_seller_attribute_value(seller.get("attributes", []), AttributeKey.YEARS_OF_EXPERIENCE)

        if req_years is None:
            result["status"] = RequirementStatus.INSUFFICIENT_INFORMATION.value
            result["reason"] = "Requirement specifies experience required but threshold is unknown."
            return result

        if seller_years is None:
            result["status"] = RequirementStatus.INSUFFICIENT_INFORMATION.value
            result["reason"] = "Seller experience data missing."
            return result

        # Check for relaxation
        tender_allows_startup = req.get("startup_relaxation", False)
        tender_allows_mse = req.get("mse_relaxation", False)

        is_startup = str(get_seller_attribute_value(seller.get("attributes", []), AttributeKey.STARTUP_STATUS)).lower() == "true"
        is_mse = str(get_seller_attribute_value(seller.get("attributes", []), AttributeKey.MSE_STATUS)).lower() == "true"

        # Check if seller meets the requirement
        if seller_years >= req_years:
            result["status"] = RequirementStatus.PASS.value
            result["reason"] = f"Seller has {seller_years} years experience, requirement is {req_years} years."
        else:
            # Apply relaxation if applicable
            if tender_allows_startup and is_startup:
                result["status"] = RequirementStatus.PASS_WITH_RELAXATION.value
                result["relaxation_applied"] = RelaxationRule.STARTUP_EXPERIENCE_EXEMPTION.value
                result["reason"] = "Experience relaxed for DPIIT recognized Startup."
            elif tender_allows_mse and is_mse:
                result["status"] = RequirementStatus.PASS_WITH_RELAXATION.value
                result["relaxation_applied"] = RelaxationRule.MSE_EXPERIENCE_EXEMPTION.value
                result["reason"] = "Experience relaxed for MSE seller."
            elif req.get("relaxation_conflict") or self._missing_relaxation_status(req,seller):
                result["status"] = RequirementStatus.REVIEW_REQUIRED.value
                result["reason"] = "Exemption evidence conflicts or seller MSE/Startup status is missing; review before rejection."
            else:
                result["status"] = RequirementStatus.FAIL.value
                result["reason"] = f"Seller has {seller_years} years experience, requirement is {req_years} years."

        return result

    def _evaluate_turnover(self, req: Dict[str, Any], seller: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        if req.get("applies_to", "BIDDER") not in ("BIDDER", "SELLER"):
            result["status"] = RequirementStatus.REVIEW_REQUIRED.value
            result["reason"] = "Turnover applies to an OEM, an alternative entity, or an unspecified entity; bidder turnover alone cannot verify it."
            return result
        req_value = req.get("value_number")
        seller_value = get_seller_attribute_value(seller.get("attributes", []), AttributeKey.ANNUAL_TURNOVER)

        if req_value is None:
            result["status"] = RequirementStatus.INSUFFICIENT_INFORMATION.value
            result["reason"] = "Turnover threshold unknown in tender."
            return result

        if seller_value is None:
            result["status"] = RequirementStatus.INSUFFICIENT_INFORMATION.value
            result["reason"] = "Seller turnover data missing."
            return result

        # Check for relaxation
        tender_allows_startup = req.get("startup_relaxation") == True
        tender_allows_mse = req.get("mse_relaxation") == True

        is_startup = str(get_seller_attribute_value(seller.get("attributes", []), AttributeKey.STARTUP_STATUS)).lower() == "true"
        is_mse = str(get_seller_attribute_value(seller.get("attributes", []), AttributeKey.MSE_STATUS)).lower() == "true"

        if seller_value >= req_value:
            result["status"] = RequirementStatus.PASS.value
            result["reason"] = f"Seller turnover {seller_value} >= requirement {req_value}."
        elif tender_allows_startup and is_startup:
            result["status"] = RequirementStatus.PASS_WITH_RELAXATION.value
            result["relaxation_applied"] = RelaxationRule.STARTUP_TURNOVER_EXEMPTION.value
            result["reason"] = "Turnover relaxed for Startup."
        elif tender_allows_mse and is_mse:
            result["status"] = RequirementStatus.PASS_WITH_RELAXATION.value
            result["relaxation_applied"] = RelaxationRule.MSE_TURNOVER_EXEMPTION.value
            result["reason"] = "Turnover relaxed for MSE."
        elif req.get("relaxation_conflict") or self._missing_relaxation_status(req,seller):
            result["status"] = RequirementStatus.REVIEW_REQUIRED.value
            result["reason"] = "Exemption evidence conflicts or seller MSE/Startup status is missing; review before rejection."
        else:
            result["status"] = RequirementStatus.FAIL.value
            result["reason"] = f"Seller turnover {seller_value} < requirement {req_value}."

        return result

    @staticmethod
    def _missing_relaxation_status(req,seller):
        return any(req.get(flag) is True and get_seller_attribute_value(seller.get('attributes',[]),key) is None for flag,key in [('mse_relaxation',AttributeKey.MSE_STATUS),('startup_relaxation',AttributeKey.STARTUP_STATUS)])

    def _evaluate_past_performance(self, req: Dict[str, Any], seller: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        # Simple percentage check if available
        req_pct = req.get("value_number") # e.g., 80 for 80%
        # This usually requires human review of order values vs tender estimate
        result["status"] = RequirementStatus.REVIEW_REQUIRED.value
        result["reason"] = "Past performance verification requires matching specific completed orders against tender estimate."
        return result

    def _evaluate_oem_auth(self, req: Dict[str, Any], seller: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        is_oem = get_seller_attribute_value(seller.get("attributes", []), AttributeKey.OEM_NAME) is not None
        auth_doc = get_seller_document_by_type(seller.get("documents", []), DocumentType.OEM_AUTHORIZATION)

        if is_oem:
            result["status"] = RequirementStatus.PASS.value
            result["reason"] = "Seller is an OEM."
            return result

        if not auth_doc:
            declared = str(get_seller_attribute_value(seller.get("attributes", []), AttributeKey.OEM_AUTHORIZED)).lower()
            if declared == "false":
                result["status"] = RequirementStatus.FAIL.value
                result["reason"] = "OEM authorization required; seller profile states it is not OEM-authorized."
                return result
            # Missing evidence is unknown, not a failure.
            result["status"] = RequirementStatus.REVIEW_REQUIRED.value
            result["reason"] = ("OEM authorization required; seller profile does not contain sufficient "
                                "evidence (no OEM authorization document).")
            return result

        if not is_document_valid(auth_doc):
            result["status"] = RequirementStatus.FAIL.value
            result["reason"] = f"OEM Authorization document ({auth_doc.get('filename')}) has expired."
            return result

        result["status"] = RequirementStatus.PASS.value
        result["reason"] = "Valid OEM Authorization document present."
        return result

    def _evaluate_iso(self, req: Dict[str, Any], seller: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        iso_type = req.get("value_text", "9001")
        iso_doc = get_seller_document_by_type(seller.get("documents", []), DocumentType.ISO)
        # Note: In a real system, we'd check the document display_name or metadata for specific ISO version

        if not iso_doc:
            # Absence from the profile is unknown, not proof the seller lacks the certificate.
            result["status"] = RequirementStatus.REVIEW_REQUIRED.value
            result["reason"] = f"ISO {iso_type or ''} certificate required; none recorded in seller profile.".replace("  ", " ")
            return result

        if not is_document_valid(iso_doc):
            result["status"] = RequirementStatus.FAIL.value
            result["reason"] = f"ISO certificate expired on {iso_doc.get('expiry_date')}."
            return result

        result["status"] = RequirementStatus.PASS.value
        result["reason"] = f"Valid ISO certificate present."
        return result

    def _evaluate_mse(self, req: Dict[str, Any], seller: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        if req.get("obligation", "MANDATORY").upper() in ("OPTIONAL", "INFORMATIONAL"):
            result["status"] = RequirementStatus.NOT_APPLICABLE.value
            result["reason"] = "MSE preference is not a mandatory eligibility restriction."
            return result

        mse_status=get_seller_attribute_value(seller.get("attributes", []), AttributeKey.MSE_STATUS)
        is_mse = str(mse_status).lower() == "true"
        udyam_doc = get_seller_document_by_type(seller.get("documents", []), DocumentType.Udyam)

        if mse_status is None:
            result['status']=RequirementStatus.REVIEW_REQUIRED.value
            result['reason']='Tender MSE eligibility requires seller status evidence; missing status is not an explicit false.'
            return result

        if not is_mse:
            result["status"] = RequirementStatus.FAIL.value
            result["reason"] = "Tender reserved for MSE but seller does not have MSE status."
            return result

        if not udyam_doc:
            result["status"] = RequirementStatus.REVIEW_REQUIRED.value
            result["reason"] = "MSE status claimed but Udyam certificate missing from profile."
            return result
        if not is_document_valid(udyam_doc):
            result["status"] = RequirementStatus.REVIEW_REQUIRED.value
            result["reason"] = "MSE status claimed but Udyam certificate is not verified or is expired."
            return result


        result["status"] = RequirementStatus.PASS.value
        result["reason"] = "Seller is a verified MSE with Udyam certificate."
        return result

    def _evaluate_startup(self, req: Dict[str, Any], seller: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        if req.get("obligation", "MANDATORY").upper() in ("OPTIONAL", "INFORMATIONAL"):
            result["status"] = RequirementStatus.NOT_APPLICABLE.value
            result["reason"] = "Startup preference is not a mandatory eligibility restriction."
            return result

        startup_status=get_seller_attribute_value(seller.get("attributes", []), AttributeKey.STARTUP_STATUS)
        is_startup = str(startup_status).lower() == "true"
        dpiit_doc = get_seller_document_by_type(seller.get("documents", []), DocumentType.DPIIT)

        if startup_status is None:
            result['status']=RequirementStatus.REVIEW_REQUIRED.value
            result['reason']='Tender Startup eligibility requires seller status evidence; missing status is not an explicit false.'
            return result

        if not is_startup:
            result["status"] = RequirementStatus.FAIL.value
            result["reason"] = "Seller is not a recognized Startup."
            return result

        if not dpiit_doc:
            result["status"] = RequirementStatus.REVIEW_REQUIRED.value
            result["reason"] = "Startup status claimed but DPIIT recognition document is missing from profile."
            return result

        if not is_document_valid(dpiit_doc):
            result["status"] = RequirementStatus.REVIEW_REQUIRED.value
            result["reason"] = "Startup status claimed but DPIIT recognition document is not verified or is expired."
            return result

        result["status"] = RequirementStatus.PASS.value
        result["reason"] = "Seller is a recognized Startup."
        return result

    def _evaluate_exemptible_requirement(self, req: Dict[str, Any], seller: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """EMD/ePBG logic."""
        is_mse = str(get_seller_attribute_value(seller.get("attributes", []), AttributeKey.MSE_STATUS)).lower() == "true"
        is_startup = str(get_seller_attribute_value(seller.get("attributes", []), AttributeKey.STARTUP_STATUS)).lower() == "true"

        # Tender facts from Stage 3B
        required = req.get("value_boolean") == True

        if not required:
            result["status"] = RequirementStatus.PASS.value
            result["reason"] = f"{req.get('type')} not required by tender."
            return result

        req_type = req.get("type")
        explicit_exemption = req_type == RequirementType.EMD.value and req.get("emd_exemption_allowed") is True

        if explicit_exemption and (is_mse or is_startup):
            result["status"] = RequirementStatus.PASS_WITH_RELAXATION.value
            result["reason"] = "Explicit EMD exemption is allowed by the tender and seller has MSE/Startup status."
        else:
            result["status"] = RequirementStatus.REVIEW_REQUIRED.value
            result["reason"] = f"{req_type} required; no applicable explicit exemption has been established. Payment/security evidence requires review."

        return result
        if not results:
            return EligibilityStatus.INSUFFICIENT_INFORMATION

        valid_statuses = {status.value for status in RequirementStatus}
        if any(r.get("status") not in valid_statuses for r in results):
            return EligibilityStatus.REVIEW_REQUIRED

        statuses = [r["status"] for r in results]
    def determine_overall_status(
        self,
        results: List[Dict[str, Any]],
        corpus_complete: bool = True
    ) -> EligibilityStatus:
        """Apply precedence rules to determine overall eligibility.

        Rules:
        1. ANALYSIS_INCOMPLETE if Stage 3 corpus is incomplete.
        2. NOT_ELIGIBLE if any mandatory requirement is FAIL.
        3. REVIEW_REQUIRED if any is REVIEW_REQUIRED or CONFLICT.
        4. INSUFFICIENT_INFORMATION if any is INSUFFICIENT_INFORMATION.
        5. CONDITIONALLY_ELIGIBLE if all PASS or PASS_WITH_RELAXATION but some need verification.
        6. ELIGIBLE if all PASS or PASS_WITH_RELAXATION.
        """
        if not corpus_complete:
            return EligibilityStatus.ANALYSIS_INCOMPLETE

        if not results:
            return EligibilityStatus.INSUFFICIENT_INFORMATION

        valid_statuses = {status.value for status in RequirementStatus}
        if any(r.get("status") not in valid_statuses for r in results):
            return EligibilityStatus.REVIEW_REQUIRED

        statuses = [r["status"] for r in results]

        if RequirementStatus.FAIL.value in statuses:
            return EligibilityStatus.NOT_ELIGIBLE

        if RequirementStatus.REVIEW_REQUIRED.value in statuses:
            return EligibilityStatus.REVIEW_REQUIRED

        if RequirementStatus.INSUFFICIENT_INFORMATION.value in statuses:
            return EligibilityStatus.INSUFFICIENT_INFORMATION

        if RequirementStatus.CONDITIONALLY_PASS.value in statuses:
            return EligibilityStatus.CONDITIONALLY_ELIGIBLE

        if all(status == RequirementStatus.NOT_APPLICABLE.value for status in statuses):
            return EligibilityStatus.INSUFFICIENT_INFORMATION

        return EligibilityStatus.ELIGIBLE



