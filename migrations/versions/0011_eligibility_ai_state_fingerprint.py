"""Add AI-state fingerprint to eligibility cache identity.

Revision ID: 0011_eligibility_ai_state_fingerprint
Revises: 0010_stage5_opportunity_scoring
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_eligibility_ai_state_fingerprint"
down_revision = "0010_stage5_opportunity_scoring"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "eligibility_runs",
        sa.Column(
            "ai_state_fingerprint",
            sa.String(length=64),
            nullable=False,
            server_default="0" * 64,
        ),
    )

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
            "ai_state_fingerprint",
        ],
        unique=True,
    )

    with op.batch_alter_table("eligibility_runs") as batch_op:
        batch_op.alter_column(
            "ai_state_fingerprint",
            existing_type=sa.String(length=64),
            existing_nullable=False,
            server_default=None,
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
            "ai_analysis_run_id",
        ],
        unique=True,
    )

    op.drop_column(
        "eligibility_runs",
        "ai_state_fingerprint",
    )
