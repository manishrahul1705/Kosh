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
    accepted_by_buyer: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
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


class KoshForecastRun(Base):
    __tablename__ = "kosh_forecast_runs"
    __table_args__ = (sa.CheckConstraint("status IN ('RUNNING', 'SUCCESS', 'FAILED')", name="forecast_run_status"), sa.Index("ix_kosh_forecast_runs_seller_created", "seller_id", "created_at"))
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False)
    as_of_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    horizon_weeks: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=13)
    n_paths: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    seed: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(sa.JSON, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(sa.CHAR(64), nullable=False)
    include_forecast_sales: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    buffer_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)


class KoshForecastWeek(Base):
    __tablename__ = "kosh_forecast_weeks"
    __table_args__ = (sa.UniqueConstraint("run_id", "week_index", name="uq_kosh_forecast_week"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("kosh_forecast_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    week_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    week_start: Mapped[date] = mapped_column(sa.Date, nullable=False)
    week_end: Mapped[date] = mapped_column(sa.Date, nullable=False)
    p10_closing_balance_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    p50_closing_balance_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    p90_closing_balance_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_inflow_committed_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_inflow_forecast_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_outflow_committed_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_outflow_forecast_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_inflow_revenue_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False,default=0)
    expected_inflow_addon_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False,default=0)
    expected_outflow_addon_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False,default=0)
    expected_inflow_sandbox_paise: Mapped[int] = mapped_column(sa.BigInteger,nullable=False,default=0)
    expected_outflow_sandbox_paise: Mapped[int] = mapped_column(sa.BigInteger,nullable=False,default=0)
    prob_below_buffer: Mapped[float] = mapped_column(sa.Float, nullable=False)
    expected_shortfall_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)


class KoshAlert(Base):
    __tablename__ = "kosh_alerts"
    __table_args__ = (sa.CheckConstraint("status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'SUPERSEDED')", name="kosh_alert_status"), sa.Index("ix_kosh_alerts_seller_status", "seller_id", "status"))
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False)
    run_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("kosh_forecast_runs.id", ondelete="CASCADE"), nullable=False)
    week_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    probability: Mapped[float] = mapped_column(sa.Float, nullable=False)
    expected_shortfall_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    peak_expected_shortfall_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    causes: Mapped[list[dict[str, object]]] = mapped_column(sa.JSON, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)
    acknowledged_by: Mapped[int | None] = mapped_column(sa.Integer, sa.ForeignKey("app_users.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(sa.DateTime)


class KoshBacktest(Base):
    __tablename__ = "kosh_backtests"
    __table_args__ = (sa.Index("ix_kosh_backtests_seller_created", "seller_id", "created_at"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False)
    as_of_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    windows: Mapped[list[dict[str, object]]] = mapped_column(sa.JSON, nullable=False)
    coverage_by_horizon: Mapped[dict[str, float]] = mapped_column(sa.JSON, nullable=False)
    mape_p50_inflow: Mapped[float] = mapped_column(sa.Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)

class KoshFinancingEvaluation(Base):
    __tablename__="kosh_financing_evaluations"
    id:Mapped[int]=mapped_column(PK,primary_key=True,autoincrement=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False,index=True)
    forecast_run_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("kosh_forecast_runs.id",ondelete="RESTRICT"),nullable=False)
    input_fingerprint:Mapped[str]=mapped_column(sa.CHAR(64),nullable=False)
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)

class KoshFinancingResult(Base):
    __tablename__="kosh_financing_results"
    id:Mapped[int]=mapped_column(PK,primary_key=True,autoincrement=True)
    evaluation_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("kosh_financing_evaluations.id",ondelete="CASCADE"),nullable=False,index=True)
    product_id:Mapped[str]=mapped_column(sa.String(64),nullable=False)
    scope:Mapped[str|None]=mapped_column(sa.String(128))
    status:Mapped[str]=mapped_column(sa.String(24),nullable=False)
    max_amount_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False)
    effective_annual_rate:Mapped[str|None]=mapped_column(sa.String(32))
    arrival_business_days:Mapped[int]=mapped_column(sa.Integer,nullable=False)
    reasons:Mapped[list[dict[str,object]]]=mapped_column(sa.JSON,nullable=False)
    evidence:Mapped[list[dict[str,object]]]=mapped_column(sa.JSON,nullable=False)

class KoshPlan(Base):
    __tablename__="kosh_plans"
    id:Mapped[int]=mapped_column(PK,primary_key=True,autoincrement=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False,index=True)
    forecast_run_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("kosh_forecast_runs.id",ondelete="RESTRICT"),nullable=False)
    forecast_fingerprint:Mapped[str]=mapped_column(sa.CHAR(64),nullable=False)
    planning_details:Mapped[dict[str,object]]=mapped_column(sa.JSON,nullable=False,default=dict)
    method:Mapped[str]=mapped_column(sa.String(24),nullable=False)
    status:Mapped[str]=mapped_column(sa.String(16),nullable=False)
    total_cost_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False)
    baseline_cost_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False)
    before_probabilities:Mapped[list[float]]=mapped_column(sa.JSON,nullable=False)
    after_probabilities:Mapped[list[float]]=mapped_column(sa.JSON,nullable=False)
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)

class KoshPlanLine(Base):
    __tablename__="kosh_plan_lines"
    id:Mapped[int]=mapped_column(PK,primary_key=True,autoincrement=True)
    plan_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("kosh_plans.id",ondelete="CASCADE"),nullable=False,index=True)
    product_id:Mapped[str]=mapped_column(sa.String(64),nullable=False)
    scope_ids:Mapped[list[int]]=mapped_column(sa.JSON,nullable=False)
    amount_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False)
    arrival_week:Mapped[int]=mapped_column(sa.Integer,nullable=False)
    cost_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False)
    effective_annual_rate:Mapped[str|None]=mapped_column(sa.String(32))
    required_tier:Mapped[str]=mapped_column(sa.String(2),nullable=False)
    evidence:Mapped[list[dict[str,object]]]=mapped_column(sa.JSON,nullable=False)
    status:Mapped[str]=mapped_column(sa.String(16),nullable=False)


class KoshPolicyControl(Base):
    __tablename__="kosh_policy_controls"
    id:Mapped[int]=mapped_column(PK,primary_key=True,autoincrement=True)
    scope_key:Mapped[str]=mapped_column(sa.String(64),nullable=False,unique=True)
    seller_id:Mapped[int|None]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"))
    kill_switch:Mapped[bool]=mapped_column(sa.Boolean,nullable=False,default=False)
    sandbox_fail_next:Mapped[bool]=mapped_column(sa.Boolean,nullable=False,default=False)
    max_action_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False)
    max_day_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False)
    allowlist:Mapped[list[dict]]=mapped_column(sa.JSON,nullable=False,default=list)
    updated_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)


class KoshActionIntent(Base):
    __tablename__="kosh_action_intents"
    __table_args__=(sa.CheckConstraint("status IN ('PROPOSED','APPROVED','EXECUTING','SUCCEEDED','FAILED','REJECTED','EXPIRED','BLOCKED')",name="action_intent_status"),sa.CheckConstraint("source='PLANNER' OR source LIKE 'ADDON:%'",name="action_intent_source"),sa.CheckConstraint("tier IN ('T0','T1','T2','T3','T4')",name="action_intent_tier"),sa.UniqueConstraint("plan_line_id","action_type",name="uq_action_plan_line_type"),sa.Index("ix_kosh_action_intents_seller_status","seller_id","status"))
    id:Mapped[str]=mapped_column(sa.String(36),primary_key=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False)
    source:Mapped[str]=mapped_column(sa.String(64),nullable=False)
    action_type:Mapped[str]=mapped_column(sa.String(48),nullable=False)
    params:Mapped[dict]=mapped_column(sa.JSON,nullable=False)
    plan_line_id:Mapped[int|None]=mapped_column(PK,sa.ForeignKey("kosh_plan_lines.id",ondelete="RESTRICT"),nullable=True)
    tier:Mapped[str]=mapped_column(sa.String(2),nullable=False)
    params_hash:Mapped[str]=mapped_column(sa.CHAR(64),nullable=False)
    status:Mapped[str]=mapped_column(sa.String(16),nullable=False)
    created_by_user_id:Mapped[int]=mapped_column(sa.Integer,sa.ForeignKey("app_users.id",ondelete="RESTRICT"),nullable=False)
    policy_decision:Mapped[dict]=mapped_column(sa.JSON,nullable=False,default=dict)
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)
    updated_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow,onupdate=utcnow)
    approved_at:Mapped[datetime|None]=mapped_column(sa.DateTime)
    executed_at:Mapped[datetime|None]=mapped_column(sa.DateTime)
    expires_at:Mapped[datetime|None]=mapped_column(sa.DateTime)


class KoshActionApproval(Base):
    __tablename__="kosh_action_approvals"
    jti:Mapped[str]=mapped_column(sa.String(36),primary_key=True)
    intent_id:Mapped[str]=mapped_column(sa.String(36),sa.ForeignKey("kosh_action_intents.id",ondelete="RESTRICT"),nullable=False,index=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False)
    params_hash:Mapped[str]=mapped_column(sa.CHAR(64),nullable=False)
    approver_id:Mapped[int]=mapped_column(sa.Integer,sa.ForeignKey("app_users.id",ondelete="RESTRICT"),nullable=False)
    issued_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False)
    expires_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False)
    used_at:Mapped[datetime|None]=mapped_column(sa.DateTime)
    revoked_at:Mapped[datetime|None]=mapped_column(sa.DateTime)
    otp_verified:Mapped[bool]=mapped_column(sa.Boolean,nullable=False,default=False)


class KoshOtpChallenge(Base):
    __tablename__="kosh_otp_challenges"
    __table_args__=(sa.CheckConstraint("attempts BETWEEN 0 AND 3",name="otp_attempt_limit"),)
    id:Mapped[str]=mapped_column(sa.String(36),primary_key=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False)
    intent_id:Mapped[str]=mapped_column(sa.String(36),sa.ForeignKey("kosh_action_intents.id",ondelete="RESTRICT"),nullable=False)
    approver_id:Mapped[int]=mapped_column(sa.Integer,sa.ForeignKey("app_users.id",ondelete="RESTRICT"),nullable=False)
    params_hash:Mapped[str]=mapped_column(sa.CHAR(64),nullable=False)
    code_hash:Mapped[str]=mapped_column(sa.CHAR(64),nullable=False)
    attempts:Mapped[int]=mapped_column(sa.Integer,nullable=False,default=0)
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)
    expires_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False)
    verified_at:Mapped[datetime|None]=mapped_column(sa.DateTime)
    consumed_at:Mapped[datetime|None]=mapped_column(sa.DateTime)

class KoshSandboxInbox(Base):
    __tablename__="kosh_sandbox_inbox"
    id:Mapped[str]=mapped_column(sa.String(36),primary_key=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False)
    recipient_user_id:Mapped[int]=mapped_column(sa.Integer,sa.ForeignKey("app_users.id",ondelete="RESTRICT"),nullable=False)
    kind:Mapped[str]=mapped_column(sa.String(16),nullable=False)
    intent_id:Mapped[str]=mapped_column(sa.String(36),sa.ForeignKey("kosh_action_intents.id",ondelete="RESTRICT"),nullable=False)
    encrypted_payload:Mapped[str]=mapped_column(sa.Text,nullable=False)
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)
    expires_at:Mapped[datetime|None]=mapped_column(sa.DateTime)


class KoshSharingConsent(Base):
    __tablename__="kosh_sharing_consents"
    __table_args__=(sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED')",name="sharing_consent_status"),)
    id:Mapped[int]=mapped_column(PK,primary_key=True,autoincrement=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False,index=True)
    granted_by_user_id:Mapped[int]=mapped_column(sa.Integer,sa.ForeignKey("app_users.id",ondelete="RESTRICT"),nullable=False)
    purpose:Mapped[str]=mapped_column(sa.String(48),nullable=False)
    recipient_id:Mapped[str]=mapped_column(sa.String(64),nullable=False)
    fields:Mapped[list[str]]=mapped_column(sa.JSON,nullable=False)
    expires_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False)
    status:Mapped[str]=mapped_column(sa.String(16),nullable=False)
    revoked_at:Mapped[datetime|None]=mapped_column(sa.DateTime)
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)


class KoshSandboxExecution(Base):
    __tablename__="kosh_sandbox_executions"
    __table_args__=(sa.CheckConstraint("status IN ('PENDING','SUBMITTED','SETTLED','FAILED')",name="sandbox_execution_status"),)
    id:Mapped[str]=mapped_column(sa.String(36),primary_key=True)
    intent_id:Mapped[str]=mapped_column(sa.String(36),sa.ForeignKey("kosh_action_intents.id",ondelete="RESTRICT"),nullable=False,unique=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False)
    idempotency_key:Mapped[str]=mapped_column(sa.String(128),nullable=False,unique=True)
    params_hash:Mapped[str]=mapped_column(sa.CHAR(64),nullable=False)
    adapter:Mapped[str]=mapped_column(sa.String(16),nullable=False)
    status:Mapped[str]=mapped_column(sa.String(16),nullable=False)
    expected_entries:Mapped[list]=mapped_column(sa.JSON,nullable=False,default=list)
    result:Mapped[dict]=mapped_column(sa.JSON,nullable=False,default=dict)
    history:Mapped[list]=mapped_column(sa.JSON,nullable=False,default=list)
    error:Mapped[str|None]=mapped_column(sa.Text)
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)
    updated_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)

class KoshSandboxLedgerEntry(Base):
    __tablename__="kosh_sandbox_ledger"
    __table_args__=(sa.UniqueConstraint("execution_id","entry_key",name="uq_sandbox_execution_entry"),sa.CheckConstraint("label='SANDBOX'",name="sandbox_ledger_label"),sa.CheckConstraint("status IN ('POSTED','SCHEDULED')",name="sandbox_ledger_status"))
    id:Mapped[int]=mapped_column(PK,primary_key=True,autoincrement=True)
    execution_id:Mapped[str]=mapped_column(sa.String(36),sa.ForeignKey("kosh_sandbox_executions.id",ondelete="RESTRICT"),nullable=False)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False)
    entry_key:Mapped[str]=mapped_column(sa.String(48),nullable=False)
    entry_date:Mapped[date]=mapped_column(sa.Date,nullable=False)
    amount_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False)
    kind:Mapped[str]=mapped_column(sa.String(32),nullable=False)
    invoice_id:Mapped[int|None]=mapped_column(PK,sa.ForeignKey("kosh_invoices.id",ondelete="RESTRICT"))
    receivable_reduction_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False,default=0)
    status:Mapped[str]=mapped_column(sa.String(16),nullable=False)
    label:Mapped[str]=mapped_column(sa.String(16),nullable=False,default="SANDBOX")
    posted_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)

class KoshSandboxOutbox(Base):
    __tablename__="kosh_sandbox_outbox"
    id:Mapped[str]=mapped_column(sa.String(36),primary_key=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False)
    execution_id:Mapped[str]=mapped_column(sa.String(36),sa.ForeignKey("kosh_sandbox_executions.id",ondelete="RESTRICT"),nullable=False,unique=True)
    intent_id:Mapped[str]=mapped_column(sa.String(36),sa.ForeignKey("kosh_action_intents.id",ondelete="RESTRICT"),nullable=False)
    channel:Mapped[str]=mapped_column(sa.String(16),nullable=False)
    recipient_ref:Mapped[str]=mapped_column(sa.String(128),nullable=False)
    body:Mapped[str]=mapped_column(sa.Text,nullable=False)
    status:Mapped[str]=mapped_column(sa.String(16),nullable=False)
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)


class KoshCashEvent(Base):
    __tablename__="kosh_cash_events"
    __table_args__=(sa.UniqueConstraint("seller_id","source_module","event_type","evidence_ref",name="uq_cash_event_evidence"),sa.CheckConstraint("status IN ('PROPOSED','CONFIRMED','REJECTED')",name="cash_event_status"),sa.CheckConstraint("event_type IN ('EXPECTED_RECEIVABLE','SCHEDULED_PAYABLE','COST_CHANGE','FINANCING_NEED')",name="cash_event_type"),sa.CheckConstraint("amount_paise>=0",name="cash_event_amount"),)
    id:Mapped[int]=mapped_column(PK,primary_key=True,autoincrement=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False,index=True)
    event_type:Mapped[str]=mapped_column(sa.String(32),nullable=False)
    cost_direction:Mapped[str|None]=mapped_column(sa.String(8))
    source_module:Mapped[str]=mapped_column(sa.String(48),nullable=False)
    evidence_ref:Mapped[str]=mapped_column(sa.String(160),nullable=False)
    event_date:Mapped[date]=mapped_column(sa.Date,nullable=False)
    amount_paise:Mapped[int]=mapped_column(sa.BigInteger,nullable=False)
    status:Mapped[str]=mapped_column(sa.String(16),nullable=False,default="PROPOSED")
    created_by_user_id:Mapped[int]=mapped_column(sa.Integer,sa.ForeignKey("app_users.id"),nullable=False)
    confirmed_by_user_id:Mapped[int|None]=mapped_column(sa.Integer,sa.ForeignKey("app_users.id"))
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)
    confirmed_at:Mapped[datetime|None]=mapped_column(sa.DateTime)


class KoshAddonDraft(Base):
    __tablename__="kosh_addon_drafts"
    id:Mapped[int]=mapped_column(PK,primary_key=True,autoincrement=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False,index=True)
    module:Mapped[str]=mapped_column(sa.String(48),nullable=False)
    kind:Mapped[str]=mapped_column(sa.String(48),nullable=False)
    params:Mapped[dict]=mapped_column(sa.JSON,nullable=False)
    body:Mapped[str]=mapped_column(sa.Text,nullable=False)
    evidence_hash:Mapped[str]=mapped_column(sa.CHAR(64),nullable=False)
    status:Mapped[str]=mapped_column(sa.String(24),nullable=False,default="DRAFT")
    created_by_user_id:Mapped[int]=mapped_column(sa.Integer,sa.ForeignKey("app_users.id"),nullable=False)
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)

class KoshCollectionTerms(Base):
    __tablename__="kosh_collection_terms"
    invoice_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("kosh_invoices.id",ondelete="RESTRICT"),primary_key=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False)
    acceptance_date:Mapped[date|None]=mapped_column(sa.Date,nullable=True)
    agreement_status:Mapped[str]=mapped_column(sa.String(16),nullable=False,default="UNKNOWN")
    agreed_days:Mapped[int|None]=mapped_column(sa.Integer,nullable=True)
    supplier_mse:Mapped[bool|None]=mapped_column(sa.Boolean,nullable=True)
    evidence_ref:Mapped[str|None]=mapped_column(sa.String(160),nullable=True)


class KoshOperationRecord(Base):
    __tablename__="kosh_operation_records"
    id:Mapped[int]=mapped_column(PK,primary_key=True,autoincrement=True)
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False,index=True)
    kind:Mapped[str]=mapped_column(sa.String(48),nullable=False)
    evidence_ref:Mapped[str]=mapped_column(sa.String(160),nullable=False)
    data:Mapped[dict]=mapped_column(sa.JSON,nullable=False)
    status:Mapped[str]=mapped_column(sa.String(24),nullable=False,default="PROPOSED")
    created_by_user_id:Mapped[int]=mapped_column(sa.Integer,sa.ForeignKey("app_users.id"),nullable=False)
    created_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)
    updated_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)


class KoshModuleFlag(Base):
    __tablename__="kosh_module_flags"
    seller_id:Mapped[int]=mapped_column(PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),primary_key=True)
    module:Mapped[str]=mapped_column(sa.String(48),primary_key=True)
    enabled:Mapped[bool]=mapped_column(sa.Boolean,nullable=False,default=True)
    updated_at:Mapped[datetime]=mapped_column(sa.DateTime,nullable=False,default=utcnow)
