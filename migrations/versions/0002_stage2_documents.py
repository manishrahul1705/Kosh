"""Stage 2: Document acquisition & version management tables.

Revision ID: 0002_stage2
Revises: 0001_initial
Create Date: 2026-10-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_stage2"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    # Create tender_documents table (without FK to document_versions yet)
    op.create_table(
        "tender_documents",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("tender_id", PK, nullable=False),
        sa.Column("document_key", sa.String(length=128), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("current_version_id", PK, nullable=True),
        sa.Column("discovered_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tenders.id"],
            name=op.f("fk_tender_documents_tender_id_tenders"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_documents")),
    )
    op.create_index(op.f("ix_tender_documents_tender_id"), "tender_documents", ["tender_id"])
    op.create_index(
        "ix_tender_documents_tender_document_key",
        "tender_documents",
        ["tender_id", "document_key"]
    )
    op.create_index(op.f("ix_tender_documents_type"), "tender_documents", ["document_type"])
    op.create_index(op.f("ix_tender_documents_is_active"), "tender_documents", ["is_active"])

    # Create document_versions table
    op.create_table(
        "document_versions",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("document_id", PK, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("extension", sa.String(length=32), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("validation_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["tender_documents.id"],
            name=op.f("fk_document_versions_document_id_tender_documents"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
    )
    op.create_index(op.f("ix_document_versions_document_id"), "document_versions", ["document_id"])
    op.create_index(
        "ix_document_versions_document_sha256",
        "document_versions",
        ["document_id", "sha256"]
    )
    op.create_index(op.f("ix_document_versions_validation"), "document_versions", ["validation_status"])

    # Add FK from tender_documents.current_version_id to document_versions.id
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table("tender_documents", schema=None) as batch_op:
        batch_op.create_foreign_key(
            op.f("fk_tender_documents_current_version_id_document_versions"),
            "document_versions",
            ["current_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_tender_documents_current_version_id"),
            ["current_version_id"]
        )

    # Create document_events table
    op.create_table(
        "document_events",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("document_id", PK, nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("old_version_id", PK, nullable=True),
        sa.Column("new_version_id", PK, nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("collection_run_id", PK, nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["tender_documents.id"],
            name=op.f("fk_document_events_document_id_tender_documents"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["old_version_id"], ["document_versions.id"],
            name=op.f("fk_document_events_old_version_id_document_versions"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["new_version_id"], ["document_versions.id"],
            name=op.f("fk_document_events_new_version_id_document_versions"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["collection_run_id"], ["collection_runs.id"],
            name=op.f("fk_document_events_collection_run_id_collection_runs"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_events")),
    )
    op.create_index(op.f("ix_document_events_document_id"), "document_events", ["document_id"])
    op.create_index(
        "ix_document_events_detected",
        "document_events",
        ["document_id", "detected_at"]
    )
    op.create_index(op.f("ix_document_events_type"), "document_events", ["event_type"])

    # Create document_jobs table
    op.create_table(
        "document_jobs",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("tender_id", PK, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tenders.id"],
            name=op.f("fk_document_jobs_tender_id_tenders"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_jobs")),
    )
    op.create_index(op.f("ix_document_jobs_tender_id"), "document_jobs", ["tender_id"])
    op.create_index(op.f("ix_document_jobs_status"), "document_jobs", ["status"])
    op.create_index("ix_document_jobs_tender", "document_jobs", ["tender_id", "status"])


def downgrade() -> None:
    op.drop_table("document_jobs")
    op.drop_table("document_events")
    op.drop_table("document_versions")
    op.drop_table("tender_documents")
