"""Permission tiers for future action policy; action mapping is not implemented."""

from enum import Enum


class PermissionTier(str, Enum):
    """Separate reading, drafting, communication and sensitive execution."""

    T0_READ = "T0_READ"
    T1_DRAFT = "T1_DRAFT"
    T2_COMMUNICATE = "T2_COMMUNICATE"
    T3_MONEY_OR_DATA_SHARE = "T3_MONEY_OR_DATA_SHARE"
    T4_FORBIDDEN = "T4_FORBIDDEN"
