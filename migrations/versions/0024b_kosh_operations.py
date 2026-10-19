"""Persist seller-scoped native operational proposals."""
from alembic import op
import sqlalchemy as sa
revision="0024b_kosh_operations"
down_revision="0024a_kosh_addon_drafts"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("kosh_operation_records",sa.Column("id",sa.Integer,primary_key=True),sa.Column("seller_id",sa.Integer,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("kind",sa.String(48),nullable=False),sa.Column("evidence_ref",sa.String(160),nullable=False),sa.Column("data",sa.JSON,nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("created_by_user_id",sa.Integer,sa.ForeignKey("app_users.id"),nullable=False),sa.Column("created_at",sa.DateTime,nullable=False),sa.Column("updated_at",sa.DateTime,nullable=False))
    op.create_index("ix_kosh_operation_records_seller_id","kosh_operation_records",["seller_id"])
    op.add_column("kosh_cash_events",sa.Column("cost_direction",sa.String(8)))
def downgrade():
    op.drop_column("kosh_cash_events","cost_direction");op.drop_table("kosh_operation_records")
