"""THE central field registry: every Stage 3B field, its type and its label aliases.

Add a field or a new GeM label wording HERE (nothing else hard-codes labels).
Aliases were taken from the labels actually observed in stored GeM bid PDFs.

``sections``  - label is only meaningful inside these Stage 3A sections
                (normalized headings), e.g. the bare "Required" row under
                "EMD Detail". Such matches have strength SECTION_TABLE.
``text_label``- also look for "<label> <value>" lines in page text (EXACT_LABEL);
                only for distinctive multi-word labels.
``merge``     - LIST fields: candidates are unioned instead of compared.
``strict``    - any disagreement is a CONFLICT (no text-tier override), e.g. bid number.
Fields without table aliases are produced by the special rules in rules_text.py
(documents list, consignee table, ATC clauses, certificates, warranty text...).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.fields.constants import ValueType as V
from app.fields.labels import Alias, contains, exact, prefix

EMD_SECTIONS = ("emd detail", "emd details")
EPBG_SECTIONS = ("epbg detail", "epbg details")
TECH_SECTIONS = ("technical specifications", "technical specification")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    group: str
    value_type: str
    aliases: tuple[Alias, ...] = ()
    sections: tuple[str, ...] | None = None
    text_label: bool = False
    default_unit: str | None = None
    merge: bool = False
    strict: bool = False
    description: str = ""
    extra: dict = field(default_factory=dict)


FIELDS: tuple[FieldSpec, ...] = (
    # ---- IDENTITY ------------------------------------------------------------------
    FieldSpec("bid_number", "IDENTITY", V.TEXT.value, strict=True,
              description="Stage 1 bid number; cross-checked against 'Bid Number:' printed in the PDF"),
    FieldSpec("document_version_id", "IDENTITY", V.INTEGER.value, strict=True),
    FieldSpec("document_type", "IDENTITY", V.TEXT.value, strict=True),
    FieldSpec("document_version_number", "IDENTITY", V.INTEGER.value, strict=True),
    FieldSpec("bid_document_date", "IDENTITY", V.DATE.value, description="'Dated:' on the bid document"),
    # ---- ITEM ----------------------------------------------------------------------
    FieldSpec("item_category", "ITEM", V.TEXT.value, exact("Item Category"), text_label=True),
    FieldSpec("item_description", "ITEM", V.LIST.value, merge=True,
              description="Item title(s) printed just before 'Technical Specifications'"),
    FieldSpec("total_quantity", "ITEM", V.INTEGER.value, exact("Total Quantity"), text_label=True),
    FieldSpec("estimated_bid_value", "ITEM", V.MONEY.value,
              exact("Estimated Bid Value") + prefix("Estimated Bid Value in INR")),
    # ---- BUYER ---------------------------------------------------------------------
    FieldSpec("ministry_state", "BUYER", V.TEXT.value, exact("Ministry/State Name"), text_label=True),
    FieldSpec("department", "BUYER", V.TEXT.value, exact("Department Name"), text_label=True),
    FieldSpec("organisation", "BUYER", V.TEXT.value, exact("Organisation Name", "Organization Name"),
              text_label=True),
    FieldSpec("office", "BUYER", V.TEXT.value, exact("Office Name"), text_label=True),
    # ---- DATES ---------------------------------------------------------------------
    FieldSpec("bid_end_datetime", "DATES", V.DATETIME.value, exact("Bid End Date/Time"), text_label=True),
    FieldSpec("bid_opening_datetime", "DATES", V.DATETIME.value, exact("Bid Opening Date/Time"), text_label=True),
    FieldSpec("bid_offer_validity_days", "DATES", V.INTEGER.value, prefix("Bid Offer Validity")),
    FieldSpec("contract_period", "DATES", V.DURATION.value, exact("Contract Period")),
    # ---- BID STRUCTURE -------------------------------------------------------------
    FieldSpec("bid_type", "BID_STRUCTURE", V.TEXT.value, exact("Type of Bid"), text_label=True),
    FieldSpec("evaluation_method", "BID_STRUCTURE", V.TEXT.value, exact("Evaluation Method"), text_label=True),
    FieldSpec("bid_to_ra_enabled", "BID_STRUCTURE", V.BOOL.value, exact("Bid to RA enabled"), text_label=True),
    FieldSpec("inspection_required", "BID_STRUCTURE", V.BOOL.value, prefix("Inspection Required")),
    FieldSpec("technical_clarification_days", "BID_STRUCTURE", V.DURATION.value,
              prefix("Time allowed for Technical Clarifications")),
    FieldSpec("payment_timelines", "BID_STRUCTURE", V.TEXT.value, exact("Payment Timelines")),
    # ---- COMMERCIAL / SECURITY -----------------------------------------------------
    FieldSpec("emd_required", "COMMERCIAL", V.BOOL.value, exact("Required", "EMD Required"),
              sections=EMD_SECTIONS),
    FieldSpec("emd_amount", "COMMERCIAL", V.MONEY.value, exact("EMD Amount")),
    FieldSpec("emd_percentage", "COMMERCIAL", V.PERCENT.value, prefix("EMD Percentage")),
    FieldSpec("emd_advisory_bank", "COMMERCIAL", V.TEXT.value, exact("Advisory Bank"), sections=EMD_SECTIONS),
    FieldSpec("emd_exemption_allowed", "COMMERCIAL", V.BOOL.value, prefix("EMD Exemption"),
              description="Explicit 'EMD EXEMPTION:' clause (eligibility to claim it is Stage 4)"),
    FieldSpec("epbg_required", "COMMERCIAL", V.BOOL.value, exact("Required", "ePBG Required"),
              sections=EPBG_SECTIONS),
    FieldSpec("epbg_percentage", "COMMERCIAL", V.PERCENT.value, prefix("ePBG Percentage")),
    FieldSpec("epbg_duration", "COMMERCIAL", V.DURATION.value, prefix("Duration of ePBG required"),
              default_unit="MONTHS"),
    FieldSpec("epbg_advisory_bank", "COMMERCIAL", V.TEXT.value, exact("Advisory Bank"), sections=EPBG_SECTIONS),
    # ---- PERFORMANCE / EXPERIENCE ----------------------------------------------------
    FieldSpec("experience_required", "PERFORMANCE", V.BOOL.value,
              prefix("Past Experience of Similar Services required")),
    FieldSpec("experience_years", "PERFORMANCE", V.DURATION.value, prefix("Years of Past Experience Required"),
              default_unit="YEARS"),
    FieldSpec("past_performance_required", "PERFORMANCE", V.BOOL.value),
    FieldSpec("past_performance_percentage", "PERFORMANCE", V.PERCENT.value, exact("Past Performance")),
    FieldSpec("bidder_turnover_required", "PERFORMANCE", V.BOOL.value),
    FieldSpec("bidder_turnover_amount", "PERFORMANCE", V.MONEY.value,
              prefix("Minimum Average Annual Turnover of the bidder")),
    FieldSpec("oem_turnover_required", "PERFORMANCE", V.BOOL.value),
    FieldSpec("oem_turnover_amount", "PERFORMANCE", V.MONEY.value, prefix("OEM Average Turnover")),
    # ---- PREFERENCES / EXEMPTIONS ------------------------------------------------------
    FieldSpec("mse_purchase_preference", "PREFERENCES", V.BOOL.value, exact("MSE Purchase Preference"),
              text_label=True),
    FieldSpec("mse_price_preference_percent", "PREFERENCES", V.PERCENT.value,
              contains("Purchase Preference to MSE OEMs Service Provider available upto price within")),
    FieldSpec("mse_quantity_preference_percent", "PREFERENCES", V.PERCENT.value,
              contains("Percentage of Bid quantity amount for MSE")),
    FieldSpec("mii_purchase_preference", "PREFERENCES", V.BOOL.value, exact("MII Purchase Preference"),
              text_label=True),
    FieldSpec("mii_price_preference_percent", "PREFERENCES", V.PERCENT.value,
              contains("Purchase Preference to MII sellers")),
    FieldSpec("mii_quantity_preference_percent", "PREFERENCES", V.PERCENT.value,
              contains("Maximum Percentage of Bid quantity for MII purchase preference")),
    FieldSpec("mse_experience_turnover_relaxation", "PREFERENCES", V.BOOL.value,
              prefix("MSE Relaxation for Years of Experience", "MSE Exemption for Years of Experience")),
    FieldSpec("startup_experience_turnover_relaxation", "PREFERENCES", V.BOOL.value,
              prefix("Startup Relaxation for Years of Experience", "Startup Exemption for Years of Experience")),
    # ---- DOCUMENTS ---------------------------------------------------------------------
    FieldSpec("documents_required_from_seller", "DOCUMENTS", V.LIST.value,
              exact("Document required from seller", "Documents required from seller"), merge=True),
    # ---- OEM / AUTHORIZATION -------------------------------------------------------------
    FieldSpec("oem_authorization_required", "OEM", V.BOOL.value),
    FieldSpec("manufacturer_authorization_required", "OEM", V.BOOL.value),
    # ---- CERTIFICATES --------------------------------------------------------------------
    FieldSpec("certificate_requirements", "CERTIFICATES", V.LIST.value, merge=True),
    # ---- DELIVERY / CONSIGNEE ------------------------------------------------------------
    FieldSpec("delivery_period", "DELIVERY", V.DURATION.value, default_unit="DAYS",
              description="Delivery Days column of the consignee table (uniform value)"),
    FieldSpec("consignee_details", "DELIVERY", V.LIST.value, merge=True),
    FieldSpec("delivery_locations", "DELIVERY", V.LIST.value, merge=True),
    FieldSpec("quantity_by_consignee", "DELIVERY", V.LIST.value, merge=True),
    # ---- WARRANTY ------------------------------------------------------------------------
    FieldSpec("warranty_required", "WARRANTY", V.BOOL.value),
    FieldSpec("warranty_period", "WARRANTY", V.DURATION.value,
              exact("Warranty", "Warranty of required product", "Warranty Period"), sections=TECH_SECTIONS),
    # ---- ATC -----------------------------------------------------------------------------
    FieldSpec("buyer_added_atc_present", "ATC", V.BOOL.value),
    FieldSpec("buyer_added_atc_clauses", "ATC", V.LIST.value, merge=True),
    # ---- OTHER ---------------------------------------------------------------------------
    FieldSpec("arbitration_clause", "OTHER", V.BOOL.value, exact("Arbitration Clause"), text_label=True),
    FieldSpec("mediation_clause", "OTHER", V.BOOL.value, exact("Mediation Clause"), text_label=True),
)

BY_NAME: dict[str, FieldSpec] = {f.name: f for f in FIELDS}
assert len(BY_NAME) == len(FIELDS), "duplicate field name in registry"

# Known section headings (normalized) used by the special rules.
ATC_START_SECTIONS = ("buyer added bid specific terms and conditions", "buyer added bid specific atc")
ATC_END_SECTIONS = ("disclaimer",)
CERTIFICATE_SECTIONS = ("certificates", "certificate")
WARRANTY_SECTIONS = ("warranty",)

# Items of the "Document required from seller" list that imply a requirement.
DOC_LIST_IMPLIES: dict[str, tuple[str, ...]] = {
    "experience_required": ("experience criteria",),
    "past_performance_required": ("past performance",),
    "bidder_turnover_required": ("bidder turnover",),
    "oem_turnover_required": ("oem annual turnover", "oem turnover"),
    "oem_authorization_required": ("oem authorization certificate", "oem authorisation certificate",
                                   "oem authorization", "oem authorisation"),
    "manufacturer_authorization_required": ("manufacturer authorization", "manufacturer authorisation"),
}
