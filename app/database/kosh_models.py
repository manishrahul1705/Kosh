"""Additive business ledger, consent and audit storage for Kosh."""

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models import Base, PK
from app.utils.dates import utcnow


class KoshCounterparty(Base):
    """Kosh counterparties."""

    __tablename__ = "kosh_counterparties"
    __table_args__ = (
        sa.UniqueConstraint("seller_id", "name", "kind", name="uq_kosh_counterparty_identity"),
        sa.UniqueConstraint("seller_id", "id", name="uq_kosh_counterparty_seller_id"),
        sa.CheckConstraint("kind IN ('CUSTOMER', 'SUPPLIER')", name="counterparty_kind"),
        sa.Index("ix_kosh_counterparties_seller_id", "seller_id"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    gstin: Mapped[str | None] = mapped_column(sa.String(15), nullable=True)
    is_cpse: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    treds_onboarded: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class KoshInvoice(Base):
    """Kosh invoices."""

    __tablename__ = "kosh_invoices"
    __table_args__ = (
        sa.UniqueConstraint("seller_id", "direction", "counterparty_id", "invoice_number", name="uq_kosh_invoice_identity"),
        sa.ForeignKeyConstraint(["seller_id", "counterparty_id"], ["kosh_counterparties.seller_id", "kosh_counterparties.id"], ondelete="RESTRICT", name="fk_kosh_invoice_counterparty_seller"),
        sa.CheckConstraint("direction IN ('RECEIVABLE', 'PAYABLE')", name="invoice_direction"),
        sa.CheckConstraint("status IN ('OPEN', 'PAID', 'PARTIAL', 'DISPUTED', 'REVIEW')", name="invoice_status"),
        sa.Index("ix_kosh_invoices_seller_id", "seller_id"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False)
    counterparty_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("kosh_counterparties.id", ondelete="RESTRICT"), nullable=False)
    direction: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    invoice_number: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    invoice_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    due_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False, server_default="INR")
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    paid_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    paid_amount_paise: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    source_document_version_id: Mapped[int | None] = mapped_column(PK, sa.ForeignKey("kosh_private_document_versions.id", ondelete="SET NULL"), nullable=True)
    source_location: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class KoshObligation(Base):
    """Kosh obligations."""

    __tablename__ = "kosh_obligations"
    __table_args__ = (
        sa.CheckConstraint("kind IN ('PAYROLL', 'RENT', 'EMI', 'GST', 'TDS', 'UTILITY', 'OTHER')", name="obligation_kind"),
        sa.CheckConstraint("recurrence IN ('WEEKLY', 'MONTHLY', 'QUARTERLY', 'ONE_OFF')", name="obligation_recurrence"),
        sa.Index("ix_kosh_obligations_seller_id", "seller_id"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    label: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    recurrence: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    next_due_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    day_of_month: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class KoshConsentArtifact(Base):
    """Kosh consent artifacts."""

    __tablename__ = "kosh_consent_artifacts"
    __table_args__ = (
        sa.CheckConstraint("status IN ('ACTIVE', 'EXPIRED', 'REVOKED')", name="consent_status"),
        sa.Index("ix_kosh_consent_artifacts_seller_id", "seller_id"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False)
    granted_by_user_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False)
    purpose: Mapped[str] = mapped_column(sa.Text, nullable=False)
    data_types: Mapped[list[str]] = mapped_column(sa.JSON, nullable=False)
    data_from: Mapped[date] = mapped_column(sa.Date, nullable=False)
    data_to: Mapped[date] = mapped_column(sa.Date, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class KoshAuditEntry(Base):
    """Kosh audit entries."""

    __tablename__ = "kosh_audit_entries"
    __table_args__ = (
        sa.CheckConstraint("actor_type IN ('AGENT', 'HUMAN', 'SYSTEM')", name="audit_actor_type"),
        sa.CheckConstraint("policy_decision IN ('ALLOW', 'DENY', 'NEEDS_APPROVAL')", name="audit_policy_decision"),
        sa.Index("ix_kosh_audit_entries_seller_id", "seller_id"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int | None] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=True)
    sequence: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, unique=True)
    actor_type: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tier: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    params_hash: Mapped[str] = mapped_column(sa.CHAR(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(sa.JSON, nullable=False)
    policy_decision: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    prev_hash: Mapped[str] = mapped_column(sa.CHAR(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(sa.CHAR(64), nullable=False, unique=True)
    recorded_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class KoshPrivateDocument(Base):
    """Seller-owned document metadata, separate from public tender documents."""

    __tablename__ = "kosh_private_documents"
    __table_args__ = (
        sa.CheckConstraint("kind IN ('BANK_STATEMENT', 'SALES_INVOICE', 'PURCHASE_BILL', 'BOOKS_EXPORT', 'OTHER')", name="private_document_kind"),
        sa.CheckConstraint("status IN ('UPLOADED', 'PROCESSING', 'PROCESSED', 'REVIEW', 'REJECTED', 'FAILED')", name="private_document_status"),
        sa.Index("ix_kosh_private_documents_seller_id", "seller_id"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    original_filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    uploaded_by_user_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False)
    consent_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("kosh_consent_artifacts.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="UPLOADED")
    status_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    current_version_id: Mapped[int | None] = mapped_column(PK, sa.ForeignKey("kosh_private_document_versions.id", ondelete="SET NULL", name="fk_kosh_private_documents_current_version"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class KoshPrivateDocumentVersion(Base):
    """Immutable private bytes identified by seller and SHA-256."""

    __tablename__ = "kosh_private_document_versions"
    __table_args__ = (
        sa.UniqueConstraint("seller_id", "sha256", name="uq_kosh_private_version_seller_sha"),
        sa.Index("ix_kosh_private_document_versions_document_id", "document_id"),
        sa.Index("ix_kosh_private_document_versions_seller_id", "seller_id"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("kosh_private_documents.id", ondelete="CASCADE"), nullable=False)
    seller_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False)
    sha256: Mapped[str] = mapped_column(sa.CHAR(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    detected_format: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(sa.String(160), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)


class KoshBankTransaction(Base):
    """Normalized private bank transaction with integer-paise amounts."""

    __tablename__ = "kosh_bank_transactions"
    __table_args__ = (
        sa.UniqueConstraint("seller_id", "txn_id", name="uq_kosh_bank_transaction_identity"),
        sa.Index("ix_kosh_bank_transactions_seller_id", "seller_id"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False)
    account_ref_masked: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    txn_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    txn_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    narration: Mapped[str] = mapped_column(sa.Text, nullable=False)
    amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    balance_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    source_document_version_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("kosh_private_document_versions.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)
