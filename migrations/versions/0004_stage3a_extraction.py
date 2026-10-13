"""Stage 3A: document text / table / structure extraction.

Revision ID: 0004_stage3a_extraction
Revises: 0003_stage2b
Create Date: 2026-10-06

Purely additive: five NEW tables. No existing table, column, index or row of
Stage 1 / Stage 2 is altered or deleted. Downgrade drops only these tables.

* document_extractions  one extraction of one DocumentVersion by one extractor version
                        (partial UNIQUE (document_version_id, extractor_version) WHERE is_current)
* document_pages        per-page raw + normalized text, 1-based page_number
* document_tables       per-page tables as JSON cell grids
* document_sections     detected headings in document order
* extraction_jobs       persistent job queue (partial UNIQUE document_version_id WHERE queued)
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_stage3a_extraction"
down_revision: Union[str, None] = "0003_stage2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
QUEUED_WHERE = "status IN ('PENDING', 'RETRY')"


def _fk(table: str, column: str, ref_table: str, ondelete: str = "CASCADE") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{ref_table}.id"], name=op.f(f"fk_{table}_{column}_{ref_table}"), ondelete=ondelete
    )


def upgrade() -> None:
    op.create_table(
        "document_extractions",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("document_version_id", PK, nullable=False),
        sa.Column("document_id", PK, nullable=False),
        sa.Column("tender_id", PK, nullable=False),
        sa.Column("extractor_name", sa.String(length=40), nullable=False),
        sa.Column("extractor_version", sa.String(length=40), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("quality_status", sa.String(length=20), nullable=False),
        sa.Column("text_class", sa.String(length=20), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_file_size", sa.BigInteger(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_with_text", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_without_text", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_ocr", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_characters", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_words", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("tables_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sections_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("images_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unmapped_glyphs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text_coverage_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        _fk("document_extractions", "document_version_id", "document_versions"),
        _fk("document_extractions", "document_id", "tender_documents"),
        _fk("document_extractions", "tender_id", "tenders"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_extractions")),
    )
    op.create_index(op.f("ix_document_extractions_document_version_id"), "document_extractions", ["document_version_id"])
    op.create_index(op.f("ix_document_extractions_document_id"), "document_extractions", ["document_id"])
    op.create_index(op.f("ix_document_extractions_tender_id"), "document_extractions", ["tender_id"])
    op.create_index("ix_document_extractions_status", "document_extractions", ["status"])
    op.create_index("ix_document_extractions_quality", "document_extractions", ["quality_status"])
    op.create_index(
        "uq_document_extractions_version_current", "document_extractions",
        ["document_version_id", "extractor_version"], unique=True,
        sqlite_where=sa.text("is_current = 1"), postgresql_where=sa.text("is_current IS TRUE"),
    )

    op.create_table(
        "document_pages",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("extraction_id", PK, nullable=False),
        sa.Column("document_version_id", PK, nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meaningful_char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_text", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unmapped_glyph_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text_source", sa.String(length=10), nullable=False, server_default="NATIVE"),
        sa.Column("width", sa.Float(), nullable=True),
        sa.Column("height", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _fk("document_pages", "extraction_id", "document_extractions"),
        _fk("document_pages", "document_version_id", "document_versions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_pages")),
    )
    op.create_index(op.f("ix_document_pages_extraction_id"), "document_pages", ["extraction_id"])
    op.create_index("uq_document_pages_extraction_page", "document_pages", ["extraction_id", "page_number"], unique=True)
    op.create_index("ix_document_pages_version_page", "document_pages", ["document_version_id", "page_number"])

    op.create_table(
        "document_tables",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("extraction_id", PK, nullable=False),
        sa.Column("document_version_id", PK, nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("table_index", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("table_json", sa.Text(), nullable=False),
        sa.Column("table_text", sa.Text(), nullable=True),
        sa.Column("bbox_json", sa.Text(), nullable=True),
        sa.Column("extraction_method", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _fk("document_tables", "extraction_id", "document_extractions"),
        _fk("document_tables", "document_version_id", "document_versions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_tables")),
    )
    op.create_index(op.f("ix_document_tables_extraction_id"), "document_tables", ["extraction_id"])
    op.create_index("uq_document_tables_extraction_page_index", "document_tables",
                    ["extraction_id", "page_number", "table_index"], unique=True)
    op.create_index("ix_document_tables_version_page", "document_tables", ["document_version_id", "page_number"])

    op.create_table(
        "document_sections",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("extraction_id", PK, nullable=False),
        sa.Column("document_version_id", PK, nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=False),
        sa.Column("normalized_heading", sa.String(length=255), nullable=False),
        sa.Column("heading_level", sa.Integer(), nullable=True),
        sa.Column("detection_method", sa.String(length=30), nullable=False),
        sa.Column("char_offset", sa.Integer(), nullable=True),
        sa.Column("top", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _fk("document_sections", "extraction_id", "document_extractions"),
        _fk("document_sections", "document_version_id", "document_versions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_sections")),
    )
    op.create_index(op.f("ix_document_sections_extraction_id"), "document_sections", ["extraction_id"])
    op.create_index("uq_document_sections_extraction_sequence", "document_sections",
                    ["extraction_id", "sequence"], unique=True)
    op.create_index("ix_document_sections_normalized", "document_sections", ["normalized_heading"])

    op.create_table(
        "extraction_jobs",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("document_version_id", PK, nullable=False),
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
        sa.Column("extraction_id", PK, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        _fk("extraction_jobs", "document_version_id", "document_versions"),
        _fk("extraction_jobs", "extraction_id", "document_extractions", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_jobs")),
    )
    op.create_index(op.f("ix_extraction_jobs_document_version_id"), "extraction_jobs", ["document_version_id"])
    op.create_index(op.f("ix_extraction_jobs_extraction_id"), "extraction_jobs", ["extraction_id"])
    op.create_index("ix_extraction_jobs_status_next_retry", "extraction_jobs", ["status", "next_retry_at"])
    op.create_index(
        "uq_extraction_jobs_version_queued", "extraction_jobs", ["document_version_id"], unique=True,
        sqlite_where=sa.text(QUEUED_WHERE), postgresql_where=sa.text(QUEUED_WHERE),
    )


def downgrade() -> None:
    # Only the Stage 3A tables; Stage 1/2 data is never touched.
    op.drop_table("extraction_jobs")
    op.drop_table("document_sections")
    op.drop_table("document_tables")
    op.drop_table("document_pages")
    op.drop_table("document_extractions")
