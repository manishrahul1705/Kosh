"""Initial Stage 1 schema: tenders, tender_changes, collection_runs.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "collection_runs",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("pages_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bids_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_bids", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_bids", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_bids", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_runs")),
    )
    op.create_index(op.f("ix_collection_runs_started_at"), "collection_runs", ["started_at"])
    op.create_index(op.f("ix_collection_runs_status"), "collection_runs", ["status"])

    op.create_table(
        "tenders",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("bid_number", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("bid_type", sa.String(length=32), nullable=True),
        sa.Column("buyer_name", sa.Text(), nullable=True),
        sa.Column("ministry", sa.Text(), nullable=True),
        sa.Column("department", sa.Text(), nullable=True),
        sa.Column("organisation", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=512), nullable=True),
        sa.Column("quantity", sa.BigInteger(), nullable=True),
        sa.Column("estimated_value", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("bid_end_at", sa.DateTime(), nullable=True),
        sa.Column("bid_opening_at", sa.DateTime(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_internal_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(), nullable=True),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenders")),
    )
    op.create_index(op.f("ix_tenders_bid_number"), "tenders", ["bid_number"], unique=True)
    op.create_index(op.f("ix_tenders_status"), "tenders", ["status"])
    op.create_index(op.f("ix_tenders_bid_end_at"), "tenders", ["bid_end_at"])
    op.create_index(op.f("ix_tenders_first_seen_at"), "tenders", ["first_seen_at"])
    op.create_index(op.f("ix_tenders_category"), "tenders", ["category"])

    op.create_table(
        "tender_changes",
        sa.Column("id", PK, autoincrement=True, nullable=False),
        sa.Column("tender_id", PK, nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("collection_run_id", PK, nullable=True),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tenders.id"],
            name=op.f("fk_tender_changes_tender_id_tenders"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_run_id"], ["collection_runs.id"],
            name=op.f("fk_tender_changes_collection_run_id_collection_runs"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_changes")),
    )
    op.create_index(op.f("ix_tender_changes_tender_id"), "tender_changes", ["tender_id"])
    op.create_index(op.f("ix_tender_changes_collection_run_id"), "tender_changes", ["collection_run_id"])
    op.create_index("ix_tender_changes_tender_detected", "tender_changes", ["tender_id", "detected_at"])


def downgrade() -> None:
    op.drop_table("tender_changes")
    op.drop_table("tenders")
    op.drop_table("collection_runs")
