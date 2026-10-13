"""Stage 3B: deterministic tender field extraction.

Revision ID: 0005_stage3b_tender_fields
Revises: 0004_stage3a_extraction
Create Date: 2026-10-06

Purely additive: four NEW tables. No Stage 1 / 2 / 3A table, column, index or
row is altered or deleted. Downgrade drops only these tables.

* tender_field_extractions  one run per (Stage 3A extraction, field extractor version);
                            partial UNIQUE (stage3a_extraction_id, extractor_version) WHERE is_current
* tender_field_values       one row per registry field per run (UNKNOWN fields included)
* tender_field_evidence     every candidate with provenance (page/table/row/section/rule/raw value)
* field_extraction_jobs     persistent queue; partial UNIQUE stage3a_extraction_id WHERE queued
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_stage3b_tender_fields"
down_revision: Union[str, None] = "0004_stage3a_extraction"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
QUEUED_WHERE = "status IN ('PENDING', 'RETRY')"


def _fk(table: str, column: str, ref_table: str, ondelete: str = "CASCADE") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{ref_table}.id"],
                                   name=op.f(f"fk_{table}_{column}_{ref_table}"), ondelete=ondelete)


def upgrade() -> None:
    op.create_table(
        "tender_field_extractions",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("stage3a_extraction_id", PK, nullable=False),
        sa.Column("document_version_id", PK, nullable=False),
        sa.Column("document_id", PK, nullable=False),
        sa.Column("tender_id", PK, nullable=False),
        sa.Column("bid_number", sa.String(length=64), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("extractor_name", sa.String(length=40), nullable=False),
        sa.Column("extractor_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("fields_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fields_resolved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fields_unknown", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fields_conflict", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        _fk("tender_field_extractions", "stage3a_extraction_id", "document_extractions"),
        _fk("tender_field_extractions", "document_version_id", "document_versions"),
        _fk("tender_field_extractions", "document_id", "tender_documents"),
        _fk("tender_field_extractions", "tender_id", "tenders"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_field_extractions")),
    )
    op.create_index(op.f("ix_tender_field_extractions_stage3a_extraction_id"), "tender_field_extractions",
                    ["stage3a_extraction_id"])
    op.create_index(op.f("ix_tender_field_extractions_document_version_id"), "tender_field_extractions",
                    ["document_version_id"])
    op.create_index(op.f("ix_tender_field_extractions_tender_id"), "tender_field_extractions", ["tender_id"])
    op.create_index("ix_tender_field_extractions_status", "tender_field_extractions", ["status"])
    op.create_index("ix_tender_field_extractions_bid_number", "tender_field_extractions", ["bid_number"])
    op.create_index("uq_tender_field_extractions_source_current", "tender_field_extractions",
                    ["stage3a_extraction_id", "extractor_version"], unique=True,
                    sqlite_where=sa.text("is_current = 1"), postgresql_where=sa.text("is_current IS TRUE"))

    op.create_table(
        "tender_field_values",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("field_extraction_id", PK, nullable=False),
        sa.Column("tender_id", PK, nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("field_group", sa.String(length=32), nullable=False),
        sa.Column("value_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("tri_state", sa.String(length=8), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Float(), nullable=True),
        sa.Column("value_json", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=16), nullable=True),
        sa.Column("evidence_strength", sa.String(length=20), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _fk("tender_field_values", "field_extraction_id", "tender_field_extractions"),
        _fk("tender_field_values", "tender_id", "tenders"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_field_values")),
    )
    op.create_index(op.f("ix_tender_field_values_field_extraction_id"), "tender_field_values",
                    ["field_extraction_id"])
    op.create_index(op.f("ix_tender_field_values_tender_id"), "tender_field_values", ["tender_id"])
    op.create_index("uq_tender_field_values_extraction_field", "tender_field_values",
                    ["field_extraction_id", "field_name"], unique=True)
    op.create_index("ix_tender_field_values_field_text", "tender_field_values", ["field_name", "value_text"])
    op.create_index("ix_tender_field_values_field_tri", "tender_field_values", ["field_name", "tri_state"])

    op.create_table(
        "tender_field_evidence",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("field_value_id", PK, nullable=False),
        sa.Column("field_extraction_id", PK, nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("stage3a_extraction_id", PK, nullable=False),
        sa.Column("document_version_id", PK, nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("table_id", PK, nullable=True),
        sa.Column("table_index", sa.Integer(), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("section_id", PK, nullable=True),
        sa.Column("section_heading", sa.String(length=255), nullable=True),
        sa.Column("evidence_type", sa.String(length=20), nullable=False),
        sa.Column("strength", sa.String(length=20), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("source_label", sa.Text(), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("normalized_json", sa.Text(), nullable=True),
        sa.Column("value_key", sa.String(length=255), nullable=True),
        sa.Column("disposition", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _fk("tender_field_evidence", "field_value_id", "tender_field_values"),
        _fk("tender_field_evidence", "field_extraction_id", "tender_field_extractions"),
        _fk("tender_field_evidence", "stage3a_extraction_id", "document_extractions"),
        _fk("tender_field_evidence", "document_version_id", "document_versions"),
        _fk("tender_field_evidence", "table_id", "document_tables", ondelete="SET NULL"),
        _fk("tender_field_evidence", "section_id", "document_sections", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_field_evidence")),
    )
    op.create_index(op.f("ix_tender_field_evidence_field_value_id"), "tender_field_evidence", ["field_value_id"])
    op.create_index("ix_tender_field_evidence_field", "tender_field_evidence", ["field_extraction_id", "field_name"])

    op.create_table(
        "field_extraction_jobs",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("stage3a_extraction_id", PK, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("force", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("field_extraction_id", PK, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        _fk("field_extraction_jobs", "stage3a_extraction_id", "document_extractions"),
        _fk("field_extraction_jobs", "field_extraction_id", "tender_field_extractions", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_extraction_jobs")),
    )
    op.create_index(op.f("ix_field_extraction_jobs_stage3a_extraction_id"), "field_extraction_jobs",
                    ["stage3a_extraction_id"])
    op.create_index(op.f("ix_field_extraction_jobs_field_extraction_id"), "field_extraction_jobs",
                    ["field_extraction_id"])
    op.create_index("ix_field_extraction_jobs_status_next_retry", "field_extraction_jobs", ["status", "next_retry_at"])
    op.create_index("uq_field_extraction_jobs_source_queued", "field_extraction_jobs", ["stage3a_extraction_id"],
                    unique=True, sqlite_where=sa.text(QUEUED_WHERE), postgresql_where=sa.text(QUEUED_WHERE))


def downgrade() -> None:
    # Only the Stage 3B tables; Stage 1/2/3A data is never touched.
    op.drop_table("field_extraction_jobs")
    op.drop_table("tender_field_evidence")
    op.drop_table("tender_field_values")
    op.drop_table("tender_field_extractions")
