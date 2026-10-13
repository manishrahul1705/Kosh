"""Include tender metadata in opportunity scoring cache identity.

Revision ID: 0012_opportunity_tender_metadata_fingerprint
Revises: 0011_eligibility_ai_state_fingerprint
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_opportunity_tender_metadata_fingerprint"
down_revision = "0011_eligibility_ai_state_fingerprint"
branch_labels = None
depends_on = None


OLD_INDEX_COLUMNS = [
    "tender_id",
    "seller_revision_id",
    "corpus_fingerprint",
    "scoring_model_version",
    "scoring_config_fingerprint",
    "eligibility_run_id",
]

NEW_INDEX_COLUMNS = OLD_INDEX_COLUMNS + [
    "tender_metadata_fingerprint",
]


def upgrade():
    op.add_column(
        "opportunity_score_runs",
        sa.Column(
            "tender_metadata_fingerprint",
            sa.String(length=64),
            nullable=False,
            server_default="0" * 64,
        ),
    )

    op.drop_index(
        "uq_opportunity_score_run_version",
        table_name="opportunity_score_runs",
    )

    op.create_index(
        "uq_opportunity_score_run_version",
        "opportunity_score_runs",
        NEW_INDEX_COLUMNS,
        unique=True,
    )

    with op.batch_alter_table("opportunity_score_runs") as batch_op:
        batch_op.alter_column(
            "tender_metadata_fingerprint",
            existing_type=sa.String(length=64),
            existing_nullable=False,
            server_default=None,
        )


def downgrade():
    connection = op.get_bind()

    # Restoring the old index would collapse distinct historical
    # evaluations if they differ only by metadata fingerprint.
    # Refuse that downgrade rather than deleting audit history.
    duplicates = connection.execute(
        sa.text("""
            SELECT 1
            FROM opportunity_score_runs
            GROUP BY
                tender_id,
                seller_revision_id,
                corpus_fingerprint,
                scoring_model_version,
                scoring_config_fingerprint,
                eligibility_run_id
            HAVING COUNT(*) > 1
            LIMIT 1
        """)
    ).first()

    if duplicates is not None:
        raise RuntimeError(
            "Cannot downgrade: multiple historical opportunity runs "
            "share the previous cache identity. Preserve the records "
            "and remain on migration 0012."
        )

    op.drop_index(
        "uq_opportunity_score_run_version",
        table_name="opportunity_score_runs",
    )

    op.create_index(
        "uq_opportunity_score_run_version",
        "opportunity_score_runs",
        OLD_INDEX_COLUMNS,
        unique=True,
    )

    op.drop_column(
        "opportunity_score_runs",
        "tender_metadata_fingerprint",
    )