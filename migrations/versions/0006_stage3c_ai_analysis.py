"""Stage 3C: AI-assisted tender requirement interpretation.

Revision ID: 0006_stage3c_ai_analysis
Revises: 0005_stage3b_tender_fields
Create Date: 2026-10-06

Purely additive: seven NEW tables. No Stage 1 / 2 / 3A / 3B table, column, index or
row is altered or deleted. Downgrade drops only these tables.

* ai_analysis_runs         one run per (Stage 3B run, provider, model, prompt version, schema version);
                           partial UNIQUE ... WHERE is_current (history kept). No credentials stored.
* ai_evidence_chunks       bounded Stage 3A text chunks built for the run (sent / excluded + reason)
* ai_requirements          validated, evidence-grounded requirement interpretations
* ai_requirement_evidence  verified requirement -> chunk links with the quoted source text
* ai_analysis_flags        disagreement / ambiguity / restrictive-clause / review flags
* ai_analysis_jobs         persistent queue; partial UNIQUE stage3b_extraction_id WHERE queued
* ai_provider_calls        one metadata row per provider call attempt (audit, daily cost cap; no content)

(Autogenerate also proposed two indexes on document_events / document_versions that
exist in the models but not in earlier migrations; they are intentionally NOT added
here - Stage 3C does not alter Stage 1/2 tables.)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_stage3c_ai_analysis"
down_revision: Union[str, None] = "0005_stage3b_tender_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_analysis_runs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("stage3b_extraction_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("stage3a_extraction_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("document_version_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("document_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("tender_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("bid_number", sa.String(length=64), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("analyzer_name", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("chunker_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_code", sa.String(length=40), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("chunks_total", sa.Integer(), nullable=False),
        sa.Column("chunks_sent", sa.Integer(), nullable=False),
        sa.Column("input_characters", sa.Integer(), nullable=False),
        sa.Column("requirements_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("flags_count", sa.Integer(), nullable=False),
        sa.Column("ambiguities_count", sa.Integer(), nullable=False),
        sa.Column("conflicts_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("finish_reason", sa.String(length=40), nullable=True),
        sa.Column("provider_attempts", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("request_sha256", sa.String(length=64), nullable=True),
        sa.Column("response_sha256", sa.String(length=64), nullable=True),
        sa.Column("rejected_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["tender_documents.id"],
            name=op.f("fk_ai_analysis_runs_document_id_tender_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_ai_analysis_runs_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stage3a_extraction_id"],
            ["document_extractions.id"],
            name=op.f("fk_ai_analysis_runs_stage3a_extraction_id_document_extractions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stage3b_extraction_id"],
            ["tender_field_extractions.id"],
            name=op.f("fk_ai_analysis_runs_stage3b_extraction_id_tender_field_extractions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tenders.id"], name=op.f("fk_ai_analysis_runs_tender_id_tenders"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_analysis_runs")),
    )
    with op.batch_alter_table("ai_analysis_runs", schema=None) as batch_op:
        batch_op.create_index("ix_ai_analysis_runs_bid_number", ["bid_number"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_ai_analysis_runs_document_version_id"), ["document_version_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_ai_analysis_runs_stage3a_extraction_id"), ["stage3a_extraction_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_ai_analysis_runs_stage3b_extraction_id"), ["stage3b_extraction_id"], unique=False
        )
        batch_op.create_index("ix_ai_analysis_runs_status", ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_ai_analysis_runs_tender_id"), ["tender_id"], unique=False)
        batch_op.create_index(
            "uq_ai_analysis_runs_source_current",
            ["stage3b_extraction_id", "provider", "model", "prompt_version", "schema_version"],
            unique=True,
            sqlite_where=sa.text("is_current = 1"),
            postgresql_where=sa.text("is_current IS TRUE"),
        )

    op.create_table(
        "ai_analysis_jobs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("stage3b_extraction_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("force", sa.Boolean(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("analysis_run_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["ai_analysis_runs.id"],
            name=op.f("fk_ai_analysis_jobs_analysis_run_id_ai_analysis_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["stage3b_extraction_id"],
            ["tender_field_extractions.id"],
            name=op.f("fk_ai_analysis_jobs_stage3b_extraction_id_tender_field_extractions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_analysis_jobs")),
    )
    with op.batch_alter_table("ai_analysis_jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ai_analysis_jobs_analysis_run_id"), ["analysis_run_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_ai_analysis_jobs_stage3b_extraction_id"), ["stage3b_extraction_id"], unique=False
        )
        batch_op.create_index("ix_ai_analysis_jobs_status_next_retry", ["status", "next_retry_at"], unique=False)
        batch_op.create_index(
            "uq_ai_analysis_jobs_source_queued",
            ["stage3b_extraction_id"],
            unique=True,
            sqlite_where=sa.text("status IN ('PENDING', 'RETRY')"),
            postgresql_where=sa.text("status IN ('PENDING', 'RETRY')"),
        )

    op.create_table(
        "ai_evidence_chunks",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("analysis_run_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("chunk_key", sa.String(length=16), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("stage3a_extraction_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("document_version_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("section_heading", sa.String(length=255), nullable=True),
        sa.Column("table_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("sent", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["ai_analysis_runs.id"],
            name=op.f("fk_ai_evidence_chunks_analysis_run_id_ai_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name=op.f("fk_ai_evidence_chunks_document_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["document_sections.id"],
            name=op.f("fk_ai_evidence_chunks_section_id_document_sections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["stage3a_extraction_id"],
            ["document_extractions.id"],
            name=op.f("fk_ai_evidence_chunks_stage3a_extraction_id_document_extractions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["document_tables.id"],
            name=op.f("fk_ai_evidence_chunks_table_id_document_tables"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_evidence_chunks")),
    )
    with op.batch_alter_table("ai_evidence_chunks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ai_evidence_chunks_analysis_run_id"), ["analysis_run_id"], unique=False)
        batch_op.create_index("uq_ai_evidence_chunks_run_key", ["analysis_run_id", "chunk_key"], unique=True)

    op.create_table(
        "ai_requirements",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("analysis_run_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("tender_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("requirement_type", sa.String(length=40), nullable=False),
        sa.Column("model_requirement_type", sa.String(length=80), nullable=True),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("obligation", sa.Text(), nullable=True),
        sa.Column("obligation_level", sa.String(length=16), nullable=False),
        sa.Column("model_obligation_level", sa.String(length=32), nullable=True),
        sa.Column("level_adjustment", sa.String(length=40), nullable=True),
        sa.Column("condition_text", sa.Text(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("applies_to", sa.String(length=24), nullable=False),
        sa.Column("risk_flags_json", sa.Text(), nullable=True),
        sa.Column("ambiguity", sa.Text(), nullable=True),
        sa.Column("is_buyer_atc", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["ai_analysis_runs.id"],
            name=op.f("fk_ai_requirements_analysis_run_id_ai_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tenders.id"], name=op.f("fk_ai_requirements_tender_id_tenders"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_requirements")),
    )
    with op.batch_alter_table("ai_requirements", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ai_requirements_analysis_run_id"), ["analysis_run_id"], unique=False)
        batch_op.create_index("ix_ai_requirements_level", ["obligation_level"], unique=False)
        batch_op.create_index("ix_ai_requirements_run_type", ["analysis_run_id", "requirement_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_ai_requirements_tender_id"), ["tender_id"], unique=False)

    op.create_table(
        "ai_analysis_flags",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("analysis_run_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("requirement_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("flag_type", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("stage3b_field_name", sa.String(length=64), nullable=True),
        sa.Column("stage3b_value", sa.Text(), nullable=True),
        sa.Column("stage3b_evidence_strength", sa.String(length=20), nullable=True),
        sa.Column("ai_value", sa.Text(), nullable=True),
        sa.Column("chunk_keys_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["ai_analysis_runs.id"],
            name=op.f("fk_ai_analysis_flags_analysis_run_id_ai_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["ai_requirements.id"],
            name=op.f("fk_ai_analysis_flags_requirement_id_ai_requirements"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_analysis_flags")),
    )
    with op.batch_alter_table("ai_analysis_flags", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ai_analysis_flags_analysis_run_id"), ["analysis_run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ai_analysis_flags_requirement_id"), ["requirement_id"], unique=False)
        batch_op.create_index("ix_ai_analysis_flags_run_type", ["analysis_run_id", "flag_type"], unique=False)

    op.create_table(
        "ai_requirement_evidence",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("requirement_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("analysis_run_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("chunk_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("chunk_key", sa.String(length=16), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("section_heading", sa.String(length=255), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["ai_analysis_runs.id"],
            name=op.f("fk_ai_requirement_evidence_analysis_run_id_ai_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["ai_evidence_chunks.id"],
            name=op.f("fk_ai_requirement_evidence_chunk_id_ai_evidence_chunks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["ai_requirements.id"],
            name=op.f("fk_ai_requirement_evidence_requirement_id_ai_requirements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["document_sections.id"],
            name=op.f("fk_ai_requirement_evidence_section_id_document_sections"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_requirement_evidence")),
    )
    with op.batch_alter_table("ai_requirement_evidence", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ai_requirement_evidence_analysis_run_id"), ["analysis_run_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_ai_requirement_evidence_chunk_id"), ["chunk_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ai_requirement_evidence_requirement_id"), ["requirement_id"], unique=False)

    op.create_table(
        "ai_provider_calls",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("stage3b_extraction_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["ai_analysis_jobs.id"],
                                name=op.f("fk_ai_provider_calls_job_id_ai_analysis_jobs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stage3b_extraction_id"], ["tender_field_extractions.id"],
                                name=op.f("fk_ai_provider_calls_stage3b_extraction_id_tender_field_extractions"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_provider_calls")),
    )
    op.create_index("ix_ai_provider_calls_started", "ai_provider_calls", ["started_at"])
    op.create_index(op.f("ix_ai_provider_calls_job_id"), "ai_provider_calls", ["job_id"])


def downgrade() -> None:
    # Only the Stage 3C tables (children first); earlier stages are never touched.
    op.drop_table("ai_provider_calls")
    op.drop_table("ai_requirement_evidence")
    op.drop_table("ai_analysis_flags")
    op.drop_table("ai_requirements")
    op.drop_table("ai_evidence_chunks")
    op.drop_table("ai_analysis_jobs")
    op.drop_table("ai_analysis_runs")
