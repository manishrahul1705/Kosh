"""Hashed OTP challenges and encrypted local inbox delivery."""
from alembic import op
import sqlalchemy as sa
revision="0023b_kosh_otp_step_up"
down_revision="0023a_kosh_approval_tokens"
branch_labels=None
depends_on=None
PK=sa.BigInteger().with_variant(sa.Integer(),"sqlite")

def upgrade():
    op.create_table("kosh_otp_challenges",sa.Column("id",sa.String(36),primary_key=True),sa.Column("seller_id",PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("intent_id",sa.String(36),sa.ForeignKey("kosh_action_intents.id",ondelete="RESTRICT"),nullable=False),sa.Column("approver_id",sa.Integer,sa.ForeignKey("app_users.id",ondelete="RESTRICT"),nullable=False),sa.Column("params_hash",sa.CHAR(64),nullable=False),sa.Column("code_hash",sa.CHAR(64),nullable=False),sa.Column("attempts",sa.Integer,nullable=False),sa.Column("created_at",sa.DateTime,nullable=False),sa.Column("expires_at",sa.DateTime,nullable=False),sa.Column("verified_at",sa.DateTime),sa.Column("consumed_at",sa.DateTime),sa.CheckConstraint("attempts BETWEEN 0 AND 3",name="otp_attempt_limit"))
    op.create_table("kosh_sandbox_inbox",sa.Column("id",sa.String(36),primary_key=True),sa.Column("seller_id",PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("recipient_user_id",sa.Integer,sa.ForeignKey("app_users.id",ondelete="RESTRICT"),nullable=False),sa.Column("kind",sa.String(16),nullable=False),sa.Column("intent_id",sa.String(36),sa.ForeignKey("kosh_action_intents.id",ondelete="RESTRICT"),nullable=False),sa.Column("encrypted_payload",sa.Text,nullable=False),sa.Column("created_at",sa.DateTime,nullable=False),sa.Column("expires_at",sa.DateTime))

def downgrade():
    op.drop_table("kosh_sandbox_inbox");op.drop_table("kosh_otp_challenges")
