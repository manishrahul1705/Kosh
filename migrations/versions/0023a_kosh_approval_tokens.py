"""Single-use approval artifacts bound to exact intent parameters."""
from alembic import op
import sqlalchemy as sa
revision="0023a_kosh_approval_tokens"
down_revision="0023_kosh_action_intents"
branch_labels=None
depends_on=None
PK=sa.BigInteger().with_variant(sa.Integer(),"sqlite")

def upgrade():
    op.create_table("kosh_action_approvals",sa.Column("jti",sa.String(36),primary_key=True),sa.Column("intent_id",sa.String(36),sa.ForeignKey("kosh_action_intents.id",ondelete="RESTRICT"),nullable=False),sa.Column("seller_id",PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("params_hash",sa.CHAR(64),nullable=False),sa.Column("approver_id",sa.Integer,sa.ForeignKey("app_users.id",ondelete="RESTRICT"),nullable=False),sa.Column("issued_at",sa.DateTime,nullable=False),sa.Column("expires_at",sa.DateTime,nullable=False),sa.Column("used_at",sa.DateTime),sa.Column("revoked_at",sa.DateTime),sa.Column("otp_verified",sa.Boolean,nullable=False))
    op.create_index("ix_kosh_action_approvals_intent_id","kosh_action_approvals",["intent_id"])

def downgrade():op.drop_table("kosh_action_approvals")
