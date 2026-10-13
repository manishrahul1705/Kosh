"""Stage 4: Eligibility Engine Constants.

Statuses, requirement types, relaxation rules, and other constants.
"""

from enum import Enum


class EligibilityStatus(Enum):
    """Overall eligibility status."""
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    CONDITIONALLY_ELIGIBLE = "CONDITIONALLY_ELIGIBLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    ANALYSIS_INCOMPLETE = "ANALYSIS_INCOMPLETE"


class RequirementStatus(Enum):
    """Status of a single requirement."""
    PASS = "PASS"
    FAIL = "FAIL"
    PASS_WITH_RELAXATION = "PASS_WITH_RELAXATION"
    CONDITIONALLY_PASS = "CONDITIONALLY_PASS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RequirementType(Enum):
    """Types of tender requirements."""
    EXPERIENCE = "EXPERIENCE"
    TURNOVER = "TURNOVER"
    PAST_PERFORMANCE = "PAST_PERFORMANCE"
    OEM_AUTHORIZATION = "OEM_AUTHORIZATION"
    MANUFACTURER_AUTHORIZATION = "MANUFACTURER_AUTHORIZATION"
    CERTIFICATE = "CERTIFICATE"
    ISO = "ISO"
    TECHNICAL_SPECIFICATION = "TECHNICAL_SPECIFICATION"
    WARRANTY = "WARRANTY"
    DELIVERY = "DELIVERY"
    INSTALLATION = "INSTALLATION"
    TRAINING = "TRAINING"
    INSPECTION = "INSPECTION"
    SAMPLE_REQUIREMENT = "SAMPLE_REQUIREMENT"
    DEMONSTRATION = "DEMONSTRATION"
    SERVICE_SUPPORT = "SERVICE_SUPPORT"
    AMC = "AMC"
    PAYMENT = "PAYMENT"
    EMD = "EMD"
    EPBG = "EPBG"
    MSE = "MSE"
    STARTUP = "STARTUP"
    MII = "MII"
    LOCAL_CONTENT = "LOCAL_CONTENT"
    DOCUMENT_SUBMISSION = "DOCUMENT_SUBMISSION"
    DECLARATION = "DECLARATION"
    UNDERTAKING = "UNDERTAKING"
    COMPLIANCE = "COMPLIANCE"
    BUYER_ATC = "BUYER_ATC"
    OTHER = "OTHER"


class RelaxationRule(Enum):
    """Relaxation rules for MSE/Startup."""
    MSE_EXPERIENCE_EXEMPTION = "MSE_EXPERIENCE_EXEMPTION"
    MSE_TURNOVER_EXEMPTION = "MSE_TURNOVER_EXEMPTION"
    STARTUP_EXPERIENCE_EXEMPTION = "STARTUP_EXPERIENCE_EXEMPTION"
    STARTUP_TURNOVER_EXEMPTION = "STARTUP_TURNOVER_EXEMPTION"


class DocumentType(Enum):
    """Types of seller documents."""
    PAN = "PAN"
    GST = "GST"
    Udyam = "Udyam"
    DPIIT = "DPIIT"
    ITR = "ITR"
    AUDITED_FINANCIAL_STATEMENT = "AUDITED_FINANCIAL_STATEMENT"
    BALANCE_SHEET = "BALANCE_SHEET"
    EXPERIENCE_CERTIFICATE = "EXPERIENCE_CERTIFICATE"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    COMPLETION_CERTIFICATE = "COMPLETION_CERTIFICATE"
    OEM_AUTHORIZATION = "OEM_AUTHORIZATION"
    MANUFACTURER_AUTHORIZATION = "MANUFACTURER_AUTHORIZATION"
    ISO = "ISO"
    BIS = "BIS"
    QUALITY_CERTIFICATE = "QUALITY_CERTIFICATE"
    DECLARATION = "DECLARATION"
    UNDERTAKING = "UNDERTAKING"
    OTHER = "OTHER"


class AttributeKey(Enum):
    """Keys for seller attributes."""
    BUSINESS_NAME = "business_name"
    LEGAL_TYPE = "legal_type"
    PAN_STATUS = "pan_status"
    GST_REGISTRATION = "gst_registration"
    GSTIN = "gstin"
    GEM_SELLER_STATUS = "gem_seller_status"
    INCORPORATION_DATE = "incorporation_date"
    BUSINESS_AGE = "business_age"
    REGISTERED_STATE = "registered_state"
    ANNUAL_TURNOVER = "annual_turnover"
    FINANCIAL_YEAR = "financial_year"
    AUDITED_STATEMENT_AVAILABLE = "audited_statement_available"
    ITR_AVAILABLE = "itr_available"
    YEARS_OF_EXPERIENCE = "years_of_experience"
    SIMILAR_PRODUCT_EXPERIENCE = "similar_product_experience"
    GOVERNMENT_SUPPLY_EXPERIENCE = "government_supply_experience"
    COMPLETED_ORDERS = "completed_orders"
    CONTRACT_VALUE = "contract_value"
    COMPLETION_STATUS = "completion_status"
    CUSTOMER_DEPARTMENT = "customer_department"
    PRODUCT_CATEGORY = "product_category"
    OEM_NAME = "oem_name"
    OEM_AUTHORIZED = "oem_authorized"
    MANUFACTURER_AUTHORIZED = "manufacturer_authorized"
    MSE_STATUS = "mse_status"
    STARTUP_STATUS = "startup_status"
    MII_STATUS = "mii_status"
    LOCAL_CONTENT_PERCENTAGE = "local_content_percentage"


class ObligationLevel(Enum):
    """Obligation levels for requirements."""
    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"
    CONDITIONAL = "CONDITIONAL"
    INFORMATIONAL = "INFORMATIONAL"
    UNKNOWN = "UNKNOWN"


class DocumentStatus(Enum):
    """Status of seller documents."""
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    NOT_REQUIRED = "NOT_REQUIRED"
