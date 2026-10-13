"""Deterministic tender status + seller/tender matching.

* tender_status (1:1 with tenders): derived current_status LIVE / UPCOMING /
  CLOSED / CANCELLED / UNKNOWN, with status_source and last_status_check_at.
  tenders.status keeps the raw source value untouched. Existing tenders are
  backfilled with the same rules as app.services.status_service.
* tender_status_events: history of status transitions.
* seller_tender_matches: one explained match result per relevant
  (seller, tender) pair.

Additive only: the migration creates new tables and does not modify any
existing table or row.

Revision ID: 0018_tender_status_and_seller_matching
Revises: 0017_tender_analysis_read_permission
"""

from alembic import op
import sqlalchemy as sa

revision = "0018_tender_status_and_seller_matching"
down_revision = "0017_tender_analysis_read_permission"
branch_labels = None
depends_on = None

PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade():
    op.create_table(
        "tender_status",
        sa.Column("tender_id", PK, nullable=False),
        sa.Column("current_status", sa.String(20), nullable=False),
        sa.Column("status_source", sa.String(40), nullable=False),
        sa.Column("last_status_check_at", sa.DateTime(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE",
                                name="fk_tender_status_tender_id_tenders"),
        sa.PrimaryKeyConstraint("tender_id", name="pk_tender_status"),
    )
    op.create_index("ix_tender_status_current_status", "tender_status", ["current_status"])

    op.create_table(
        "tender_status_events",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("tender_id", PK, nullable=False),
        sa.Column("old_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("status_source", sa.String(40), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE",
                                name="fk_tender_status_events_tender_id_tenders"),
        sa.PrimaryKeyConstraint("id", name="pk_tender_status_events"),
    )
    op.create_index("ix_tender_status_events_tender_detected", "tender_status_events",
                    ["tender_id", "detected_at"])

    # Backfill (same precedence as status_service.derive_current_status). Timestamps are
    # naive UTC; CURRENT_TIMESTAMP is UTC on SQLite (and on PostgreSQL sessions set to UTC).
    status_case = """CASE
            WHEN status = 'CANCELLED' THEN 'CANCELLED'
            WHEN bid_end_at IS NOT NULL AND bid_end_at <= CURRENT_TIMESTAMP THEN 'CLOSED'
            WHEN status = 'CLOSED' THEN 'CLOSED'
            WHEN published_at IS NOT NULL AND published_at > CURRENT_TIMESTAMP THEN 'UPCOMING'
            WHEN status = 'ONGOING' THEN 'LIVE'
            ELSE 'UNKNOWN' END"""
    op.execute(sa.text(
        "INSERT INTO tender_status (tender_id, current_status, status_source, last_status_check_at, changed_at) "
        f"SELECT id, {status_case}, 'MIGRATION_0018_BACKFILL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM tenders"))
    op.execute(sa.text(
        "INSERT INTO tender_status_events (tender_id, old_status, new_status, status_source, detected_at) "
        "SELECT tender_id, NULL, current_status, status_source, last_status_check_at FROM tender_status"))

    op.create_table(
        "seller_tender_matches",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("seller_id", PK, nullable=False),
        sa.Column("tender_id", PK, nullable=False),
        sa.Column("seller_revision_id", PK, nullable=False),
        sa.Column("eligibility_run_id", PK, nullable=True),
        sa.Column("relevance_status", sa.String(20), nullable=False),
        sa.Column("eligibility_status", sa.String(40), nullable=True),
        sa.Column("match_status", sa.String(20), nullable=False),
        sa.Column("matched_terms_json", sa.Text(), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("tender_state_fingerprint", sa.String(64), nullable=False),
        sa.Column("matcher_version", sa.String(20), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE",
                                name="fk_seller_tender_matches_seller_id_sellers"),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE",
                                name="fk_seller_tender_matches_tender_id_tenders"),
        sa.ForeignKeyConstraint(["seller_revision_id"], ["seller_revisions.id"], ondelete="CASCADE",
                                name="fk_seller_tender_matches_seller_revision_id_seller_revisions"),
        sa.ForeignKeyConstraint(["eligibility_run_id"], ["eligibility_runs.id"], ondelete="SET NULL",
                                name="fk_seller_tender_matches_eligibility_run_id_eligibility_runs"),
        sa.PrimaryKeyConstraint("id", name="pk_seller_tender_matches"),
    )
    op.create_index("uq_seller_tender_matches_pair", "seller_tender_matches", ["seller_id", "tender_id"], unique=True)
    op.create_index("ix_seller_tender_matches_seller_status", "seller_tender_matches", ["seller_id", "match_status"])
    op.create_index("ix_seller_tender_matches_tender_id", "seller_tender_matches", ["tender_id"])


def downgrade():
    op.drop_index("ix_seller_tender_matches_tender_id", table_name="seller_tender_matches")
    op.drop_index("ix_seller_tender_matches_seller_status", table_name="seller_tender_matches")
    op.drop_index("uq_seller_tender_matches_pair", table_name="seller_tender_matches")
    op.drop_table("seller_tender_matches")
    op.drop_index("ix_tender_status_events_tender_detected", table_name="tender_status_events")
    op.drop_table("tender_status_events")
    op.drop_index("ix_tender_status_current_status", table_name="tender_status")
    op.drop_table("tender_status")
