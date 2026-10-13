"""Expand platform operator permissions.

Revision ID: 0016_platform_operator_permissions
Revises: 0015_platform_operator_grants
"""

from alembic import op
import sqlalchemy as sa

revision = "0016_platform_operator_permissions"
down_revision = "0015_platform_operator_grants"
branch_labels = None
depends_on = None

OLD_PERMISSIONS = ("DOCUMENT_JOBS_MANAGE",)

NEW_PERMISSIONS = (
    "DOCUMENT_JOBS_MANAGE",
    "TENDER_FIELDS_MANAGE",
    "AI_ANALYSIS_MANAGE",
    "COLLECTION_RUN_MANAGE",
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

    extra_permissions = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM platform_operator_grants "
            "WHERE permission != 'DOCUMENT_JOBS_MANAGE'"
        )
    ).scalar_one()

    if extra_permissions:
        raise RuntimeError(
            "Cannot downgrade: newer operator grants exist"
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
