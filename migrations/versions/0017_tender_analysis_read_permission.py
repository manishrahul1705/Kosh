"""Add tender-analysis read permission.

Revision ID: 0017_tender_analysis_read_permission
Revises: 0016_platform_operator_permissions
"""

from alembic import op
import sqlalchemy as sa

revision = "0017_tender_analysis_read_permission"
down_revision = "0016_platform_operator_permissions"
branch_labels = None
depends_on = None

OLD_PERMISSIONS = (
    "DOCUMENT_JOBS_MANAGE",
    "TENDER_FIELDS_MANAGE",
    "AI_ANALYSIS_MANAGE",
    "COLLECTION_RUN_MANAGE",
)

NEW_PERMISSIONS = OLD_PERMISSIONS + (
    "TENDER_ANALYSIS_READ",
)


def _constraint(permissions):
    values = ", ".join(
        "'" + permission + "'" for permission in permissions
    )
    return "permission IN (" + values + ")"


def upgrade():
    with op.batch_alter_table("platform_operator_grants") as batch:
        batch.drop_constraint(
            "ck_platform_operator_permission",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_platform_operator_permission",
            _constraint(NEW_PERMISSIONS),
        )


def downgrade():
    connection = op.get_bind()

    count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM platform_operator_grants "
            "WHERE permission = 'TENDER_ANALYSIS_READ'"
        )
    ).scalar_one()

    if count:
        raise RuntimeError(
            "Cannot downgrade: tender-analysis read grants exist"
        )

    with op.batch_alter_table("platform_operator_grants") as batch:
        batch.drop_constraint(
            "ck_platform_operator_permission",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_platform_operator_permission",
            _constraint(OLD_PERMISSIONS),
        )
