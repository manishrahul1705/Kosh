"""Stage 4: Seller Profile and Eligibility Engine.

Adds tables for sellers, revisions, attributes, documents, eligibility runs,
results and evidence.
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_stage4_seller_eligibility"
down_revision = "0007_tender_corpus"
branch_labels = None
depends_on = None

def upgrade():
    # PK helper matching models.py (BIGINT on PG, INTEGER on SQLite)
    PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

    # 1. Sellers table
    op.create_table(
        "sellers",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(op.f("ix_sellers_organization_id"), "sellers", ["organization_id"], unique=False)

    # 2. Seller Revisions table
    op.create_table(
        "seller_revisions",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("seller_id", PK, nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], name=op.f("fk_seller_revisions_seller_id_sellers"), ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_seller_revisions_seller_id"), "seller_revisions", ["seller_id"], unique=False)
    op.create_index(op.f("ix_seller_revisions_fingerprint"), "seller_revisions", ["fingerprint"], unique=False)
    op.create_index("uq_seller_revision_fingerprint", "seller_revisions", ["seller_id", "fingerprint"], unique=True)

    # 3. Seller Attributes table
    op.create_table(
        "seller_attributes",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("revision_id", PK, nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Float(), nullable=True),
        sa.Column("value_json", sa.Text(), nullable=True),
        sa.Column("context", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["seller_revisions.id"], name=op.f("fk_seller_attributes_revision_id_seller_revisions"), ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_seller_attributes_revision_id"), "seller_attributes", ["revision_id"], unique=False)
    op.create_index("uq_seller_attribute_key", "seller_attributes", ["revision_id", "key"], unique=True)

    # 4. Seller Documents table
    op.create_table(
        "seller_documents",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("revision_id", PK, nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("issue_date", sa.DateTime(), nullable=True),
        sa.Column("expiry_date", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["seller_revisions.id"], name=op.f("fk_seller_documents_revision_id_seller_revisions"), ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_seller_documents_revision_id"), "seller_documents", ["revision_id"], unique=False)
    op.create_index(op.f("ix_seller_documents_document_type"), "seller_documents", ["document_type"], unique=False)
    op.create_index(op.f("ix_seller_documents_expiry_date"), "seller_documents", ["expiry_date"], unique=False)

    # 5. Eligibility Runs table
    op.create_table(
        "eligibility_runs",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("tender_id", PK, nullable=False),
        sa.Column("seller_id", PK, nullable=False),
        sa.Column("seller_revision_id", PK, nullable=False),
        sa.Column("corpus_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("ai_analysis_run_id", PK, nullable=True),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("insufficient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], name=op.f("fk_eligibility_runs_tender_id_tenders"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], name=op.f("fk_eligibility_runs_seller_id_sellers"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_revision_id"], ["seller_revisions.id"], name=op.f("fk_eligibility_runs_seller_revision_id_seller_revisions"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ai_analysis_run_id"], ["ai_analysis_runs.id"], name=op.f("fk_eligibility_runs_ai_analysis_run_id_ai_analysis_runs"), ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_eligibility_runs_tender_id"), "eligibility_runs", ["tender_id"], unique=False)
    op.create_index(op.f("ix_eligibility_runs_seller_id"), "eligibility_runs", ["seller_id"], unique=False)
    op.create_index(op.f("ix_eligibility_runs_seller_revision_id"), "eligibility_runs", ["seller_revision_id"], unique=False)
    op.create_index(op.f("ix_eligibility_runs_corpus_fingerprint"), "eligibility_runs", ["corpus_fingerprint"], unique=False)
    op.create_index(op.f("ix_eligibility_runs_status"), "eligibility_runs", ["status"], unique=False)
    op.create_index("ix_eligibility_runs_tender_seller", "eligibility_runs", ["tender_id", "seller_id"], unique=False)
    op.create_index("uq_eligibility_run_version", "eligibility_runs", ["tender_id", "seller_revision_id", "corpus_fingerprint", "engine_version"], unique=True)

    # 6. Eligibility Requirement Results table
    op.create_table(
        "eligibility_requirement_results",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("run_id", PK, nullable=False),
        sa.Column("requirement_name", sa.String(length=128), nullable=False),
        sa.Column("requirement_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("relaxation_applied", sa.String(length=64), nullable=True),
        sa.Column("stage3b_field_id", PK, nullable=True),
        sa.Column("ai_requirement_id", PK, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["eligibility_runs.id"], name=op.f("fk_eligibility_requirement_results_run_id_eligibility_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage3b_field_id"], ["tender_field_values.id"], name=op.f("fk_eligibility_requirement_results_stage3b_field_id_tender_field_values"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ai_requirement_id"], ["ai_requirements.id"], name=op.f("fk_eligibility_requirement_results_ai_requirement_id_ai_requirements"), ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_eligibility_requirement_results_run_id"), "eligibility_requirement_results", ["run_id"], unique=False)

    # 7. Eligibility Evidence table
    op.create_table(
        "eligibility_evidence",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("result_id", PK, nullable=False),
        sa.Column("seller_attribute_id", PK, nullable=True),
        sa.Column("seller_document_id", PK, nullable=True),
        sa.Column("evidence_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["eligibility_requirement_results.id"], name=op.f("fk_eligibility_evidence_result_id_eligibility_requirement_results"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_attribute_id"], ["seller_attributes.id"], name=op.f("fk_eligibility_evidence_seller_attribute_id_seller_attributes"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seller_document_id"], ["seller_documents.id"], name=op.f("fk_eligibility_evidence_seller_document_id_seller_documents"), ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_eligibility_evidence_result_id"), "eligibility_evidence", ["result_id"], unique=False)

def downgrade():
    op.drop_table("eligibility_evidence")
    op.drop_table("eligibility_requirement_results")
    op.drop_table("eligibility_runs")
    op.drop_table("seller_documents")
    op.drop_table("seller_attributes")
    op.drop_table("seller_revisions")
    op.drop_table("sellers")
