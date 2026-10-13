"""Application identity and seller membership models."""

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


class AppUser(Base):
    __tablename__ = "app_users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    supabase_user_id = Column(
        String(36),
        nullable=False,
        unique=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SellerMembership(Base):
    __tablename__ = "seller_memberships"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
    )

    seller_id = Column(
        Integer,
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
    )

    role = Column(
        String(20),
        nullable=False,
    )

    status = Column(
        String(20),
        nullable=False,
        default="PENDING",
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "seller_id",
            name="uq_seller_membership_user_seller",
        ),
        CheckConstraint(
            "role IN ('OWNER', 'ADMIN', 'EDITOR', 'VIEWER', 'APPROVER')",
            name="ck_seller_membership_role",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'SUSPENDED', 'REVOKED')",
            name="ck_seller_membership_status",
        ),
        Index("ix_seller_membership_seller", "seller_id"),
        Index("ix_seller_membership_user", "user_id"),
    )
