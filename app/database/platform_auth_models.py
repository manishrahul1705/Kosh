"""Platform-level operator authorization models."""

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from app.database.models import Base


class PlatformOperatorGrant(Base):
    """Explicit, revocable platform permission grant."""

    __tablename__ = "platform_operator_grants"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    permission = Column(String(64), nullable=False)

    status = Column(String(20), nullable=False, default="ACTIVE")

    granted_by_user_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    granted_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    revoked_by_user_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="RESTRICT"),
        nullable=True,
    )

    revoked_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "permission",
            name="uq_platform_operator_user_permission",
        ),
        CheckConstraint(
            (
                "permission IN ("
                "'DOCUMENT_JOBS_MANAGE', "
                "'TENDER_FIELDS_MANAGE', "
                "'AI_ANALYSIS_MANAGE', "
                "'COLLECTION_RUN_MANAGE', "
                "'TENDER_ANALYSIS_READ'"
                ")"
            ),
            name="ck_platform_operator_permission",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'REVOKED')",
            name="ck_platform_operator_status",
        ),
        CheckConstraint(
            "(status = 'ACTIVE' AND revoked_at IS NULL "
            "AND revoked_by_user_id IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL "
            "AND revoked_by_user_id IS NOT NULL)",
            name="ck_platform_operator_revocation",
        ),
        Index("ix_platform_operator_user", "user_id"),
    )
