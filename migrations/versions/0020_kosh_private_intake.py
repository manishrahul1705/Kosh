"""Add private intake storage and append-only audit enforcement."""

from alembic import op
import sqlalchemy as sa

revision = "0020_kosh_private_intake"
down_revision = "0019_kosh_core"
branch_labels = None
depends_on = None
PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "kosh_private_documents",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer, sa.ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("consent_id", PK, sa.ForeignKey("kosh_consent_artifacts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("status_reason", sa.Text),
        sa.Column("current_version_id", PK),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("kind IN ('BANK_STATEMENT', 'SALES_INVOICE', 'PURCHASE_BILL', 'BOOKS_EXPORT', 'OTHER')", name="private_document_kind"),
        sa.CheckConstraint("status IN ('UPLOADED', 'PROCESSING', 'PROCESSED', 'REVIEW', 'REJECTED', 'FAILED')", name="private_document_status"),
    )
    op.create_index("ix_kosh_private_documents_seller_id", "kosh_private_documents", ["seller_id"])
    op.create_table(
        "kosh_private_document_versions",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("document_id", PK, sa.ForeignKey("kosh_private_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("detected_format", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(160), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("seller_id", "sha256", name="uq_kosh_private_version_seller_sha"),
    )
    op.create_index("ix_kosh_private_document_versions_document_id", "kosh_private_document_versions", ["document_id"])
    op.create_index("ix_kosh_private_document_versions_seller_id", "kosh_private_document_versions", ["seller_id"])
    with op.batch_alter_table("kosh_private_documents") as batch:
        batch.create_foreign_key("fk_kosh_private_documents_current_version", "kosh_private_document_versions", ["current_version_id"], ["id"], ondelete="SET NULL")
    op.create_table(
        "kosh_bank_transactions",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("account_ref_masked", sa.String(8), nullable=False),
        sa.Column("txn_id", sa.String(128), nullable=False),
        sa.Column("txn_date", sa.Date, nullable=False),
        sa.Column("narration", sa.Text, nullable=False),
        sa.Column("amount_paise", sa.BigInteger, nullable=False),
        sa.Column("balance_paise", sa.BigInteger, nullable=False),
        sa.Column("source_document_version_id", PK, sa.ForeignKey("kosh_private_document_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("seller_id", "txn_id", name="uq_kosh_bank_transaction_identity"),
    )
    op.create_index("ix_kosh_bank_transactions_seller_id", "kosh_bank_transactions", ["seller_id"])
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("kosh_invoices", naming_convention=naming) as batch:
        batch.drop_constraint("fk_kosh_invoices_source_document_version_id_document_versions", type_="foreignkey")
        batch.create_foreign_key("fk_kosh_invoices_source_document_version_id_kosh_private_document_versions", "kosh_private_document_versions", ["source_document_version_id"], ["id"], ondelete="SET NULL")
    op.execute("CREATE TRIGGER kosh_audit_entries_no_update BEFORE UPDATE ON kosh_audit_entries BEGIN SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY'); END")
    op.execute("CREATE TRIGGER kosh_audit_entries_no_delete BEFORE DELETE ON kosh_audit_entries BEGIN SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY'); END")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS kosh_audit_entries_no_delete")
    op.execute("DROP TRIGGER IF EXISTS kosh_audit_entries_no_update")
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("kosh_invoices", naming_convention=naming) as batch:
        batch.drop_constraint("fk_kosh_invoices_source_document_version_id_kosh_private_document_versions", type_="foreignkey")
        batch.create_foreign_key("fk_kosh_invoices_source_document_version_id_document_versions", "document_versions", ["source_document_version_id"], ["id"], ondelete="SET NULL")
    op.drop_table("kosh_bank_transactions")
    op.drop_table("kosh_private_document_versions")
    op.drop_table("kosh_private_documents")
