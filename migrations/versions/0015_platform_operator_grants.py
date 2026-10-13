"""Add platform operator permission grants.

Revision ID: 0015_platform_operator_grants
Revises: 0014_user_seller_memberships
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_platform_operator_grants"
down_revision = "0014_user_seller_memberships"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_operator_grants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("permission", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["app_users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["app_users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "user_id", "permission",
            name="uq_platform_operator_user_permission",
        ),
        sa.CheckConstraint(
            "permission IN ('DOCUMENT_JOBS_MANAGE')",
            name="ck_platform_operator_permission",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'REVOKED')",
            name="ck_platform_operator_status",
        ),
        sa.CheckConstraint(
            "(status = 'ACTIVE' AND revoked_at IS NULL "
            "AND revoked_by_user_id IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL "
            "AND revoked_by_user_id IS NOT NULL)",
            name="ck_platform_operator_revocation",
        ),
    )

    op.create_index(
        "ix_platform_operator_user",
        "platform_operator_grants",
        ["user_id"],
    )


def downgrade():
    op.drop_index(
        "ix_platform_operator_user",
        table_name="platform_operator_grants",
    )
    op.drop_table("platform_operator_grants")
