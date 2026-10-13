"""Stage 4: Include Stage 3C analysis snapshot in eligibility run identity."""

from alembic import op


revision = "0009_eligibility_ai_analysis_identity"
down_revision = "0008_stage4_seller_eligibility"
branch_labels = None
depends_on = None


def upgrade():
    # Replace the Stage 4 idempotency key so a new Stage 3C analysis
    # snapshot can produce a distinct eligibility run.
    op.drop_index(
        "uq_eligibility_run_version",
        table_name="eligibility_runs",
    )

    op.create_index(
        "uq_eligibility_run_version",
        "eligibility_runs",
        [
            "tender_id",
            "seller_revision_id",
            "corpus_fingerprint",
            "engine_version",
            "ai_analysis_run_id",
        ],
        unique=True,
    )


def downgrade():
    op.drop_index(
        "uq_eligibility_run_version",
        table_name="eligibility_runs",
    )

    op.create_index(
        "uq_eligibility_run_version",
        "eligibility_runs",
        [
            "tender_id",
            "seller_revision_id",
            "corpus_fingerprint",
            "engine_version",
        ],
        unique=True,
    )
