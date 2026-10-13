"""Persistent seller and global policy controls."""
from alembic import op
import sqlalchemy as sa
revision="0022b_kosh_policy_controls"
down_revision="0022a_kosh_plan_safety"
branch_labels=None
depends_on=None
PK=sa.BigInteger().with_variant(sa.Integer(),"sqlite")

def upgrade():
    op.create_table("kosh_policy_controls",sa.Column("id",PK,primary_key=True),sa.Column("scope_key",sa.String(64),nullable=False,unique=True),sa.Column("seller_id",PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT")),sa.Column("kill_switch",sa.Boolean,nullable=False),sa.Column("max_action_paise",sa.BigInteger,nullable=False),sa.Column("max_day_paise",sa.BigInteger,nullable=False),sa.Column("allowlist",sa.JSON,nullable=False),sa.Column("updated_at",sa.DateTime,nullable=False))

def downgrade():op.drop_table("kosh_policy_controls")
