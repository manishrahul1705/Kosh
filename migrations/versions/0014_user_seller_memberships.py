"""Add application users and seller memberships.

Revision ID: 0014_user_seller_memberships
Revises: 0013_stage6_financial_persistence
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_user_seller_memberships"
down_revision = "0013_stage6_financial_persistence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_users",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "supabase_user_id",
            sa.String(36),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "seller_memberships",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "seller_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["seller_id"],
            ["sellers.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "seller_id",
            name="uq_seller_membership_user_seller",
        ),
        sa.CheckConstraint(
            "role IN ('OWNER', 'ADMIN', 'EDITOR', 'VIEWER', 'APPROVER')",
            name="ck_seller_membership_role",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'SUSPENDED', 'REVOKED')",
            name="ck_seller_membership_status",
        ),
    )

    op.create_index(
        "ix_seller_membership_user",
        "seller_memberships",
        ["user_id"],
    )

    op.create_index(
        "ix_seller_membership_seller",
        "seller_memberships",
        ["seller_id"],
    )


def downgrade():
    op.drop_index(
        "ix_seller_membership_seller",
        table_name="seller_memberships",
    )

    op.drop_index(
        "ix_seller_membership_user",
        table_name="seller_memberships",
    )

    op.drop_table("seller_memberships")
    op.drop_table("app_users")
