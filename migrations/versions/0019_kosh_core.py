"""Create additive Kosh core tables without modifying tender data."""

from alembic import op
import sqlalchemy as sa

revision = "0019_kosh_core"
down_revision = "0018_tender_status_and_seller_matching"
branch_labels = None
depends_on = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "kosh_counterparties",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("gstin", sa.String(15), nullable=True),
        sa.Column("is_cpse", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("treds_onboarded", sa.Boolean, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("seller_id", "name", "kind", name="uq_kosh_counterparty_identity"),
        sa.UniqueConstraint("seller_id", "id", name="uq_kosh_counterparty_seller_id"),
        sa.CheckConstraint("kind IN ('CUSTOMER', 'SUPPLIER')", name="counterparty_kind"),
    )
    op.create_index("ix_kosh_counterparties_seller_id", "kosh_counterparties", ["seller_id"])
    op.create_table(
        "kosh_invoices",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("counterparty_id", PK, sa.ForeignKey("kosh_counterparties.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("invoice_number", sa.String(255), nullable=False),
        sa.Column("invoice_date", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("amount_paise", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("paid_date", sa.Date, nullable=True),
        sa.Column("paid_amount_paise", sa.BigInteger, nullable=True),
        sa.Column("source_document_version_id", PK, sa.ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_location", sa.Text, nullable=True),
        sa.Column("extraction_confidence", sa.Float, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("seller_id", "direction", "counterparty_id", "invoice_number", name="uq_kosh_invoice_identity"),
        sa.ForeignKeyConstraint(["seller_id", "counterparty_id"], ["kosh_counterparties.seller_id", "kosh_counterparties.id"], ondelete="RESTRICT", name="fk_kosh_invoice_counterparty_seller"),
        sa.CheckConstraint("direction IN ('RECEIVABLE', 'PAYABLE')", name="invoice_direction"),
        sa.CheckConstraint("status IN ('OPEN', 'PAID', 'PARTIAL', 'DISPUTED', 'REVIEW')", name="invoice_status"),
    )
    op.create_index("ix_kosh_invoices_seller_id", "kosh_invoices", ["seller_id"])
    op.create_table(
        "kosh_obligations",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("amount_paise", sa.BigInteger, nullable=False),
        sa.Column("recurrence", sa.String(16), nullable=False),
        sa.Column("next_due_date", sa.Date, nullable=False),
        sa.Column("day_of_month", sa.Integer, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("kind IN ('PAYROLL', 'RENT', 'EMI', 'GST', 'TDS', 'UTILITY', 'OTHER')", name="obligation_kind"),
        sa.CheckConstraint("recurrence IN ('WEEKLY', 'MONTHLY', 'QUARTERLY', 'ONE_OFF')", name="obligation_recurrence"),
    )
    op.create_index("ix_kosh_obligations_seller_id", "kosh_obligations", ["seller_id"])
    op.create_table(
        "kosh_consent_artifacts",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer, sa.ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("data_types", sa.JSON, nullable=False),
        sa.Column("data_from", sa.Date, nullable=False),
        sa.Column("data_to", sa.Date, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'EXPIRED', 'REVOKED')", name="consent_status"),
    )
    op.create_index("ix_kosh_consent_artifacts_seller_id", "kosh_consent_artifacts", ["seller_id"])
    op.create_table(
        "kosh_audit_entries",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("sequence", sa.BigInteger, nullable=False, unique=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.Text, nullable=True),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("tier", sa.String(32), nullable=False),
        sa.Column("params_hash", sa.CHAR(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("policy_decision", sa.String(16), nullable=False),
        sa.Column("approval_id", sa.Text, nullable=True),
        sa.Column("prev_hash", sa.CHAR(64), nullable=False),
        sa.Column("entry_hash", sa.CHAR(64), nullable=False, unique=True),
        sa.Column("recorded_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("actor_type IN ('AGENT', 'HUMAN', 'SYSTEM')", name="audit_actor_type"),
        sa.CheckConstraint("policy_decision IN ('ALLOW', 'DENY', 'NEEDS_APPROVAL')", name="audit_policy_decision"),
    )
    op.create_index("ix_kosh_audit_entries_seller_id", "kosh_audit_entries", ["seller_id"])


def downgrade() -> None:
    op.drop_table("kosh_audit_entries")
    op.drop_table("kosh_consent_artifacts")
    op.drop_table("kosh_obligations")
    op.drop_table("kosh_invoices")
    op.drop_table("kosh_counterparties")
