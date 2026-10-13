"""Add provenance-bound action intents from valid plan lines."""
from alembic import op
import sqlalchemy as sa
revision="0023_kosh_action_intents"
down_revision="0022b_kosh_policy_controls"
branch_labels=None
depends_on=None
PK=sa.BigInteger().with_variant(sa.Integer(),"sqlite")

def upgrade():
    op.create_table("kosh_action_intents",sa.Column("id",sa.String(36),primary_key=True),sa.Column("seller_id",PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("source",sa.String(64),nullable=False),sa.Column("action_type",sa.String(48),nullable=False),sa.Column("params",sa.JSON,nullable=False),sa.Column("plan_line_id",PK,sa.ForeignKey("kosh_plan_lines.id",ondelete="RESTRICT"),nullable=False),sa.Column("tier",sa.String(2),nullable=False),sa.Column("params_hash",sa.CHAR(64),nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("created_by_user_id",sa.Integer,sa.ForeignKey("app_users.id",ondelete="RESTRICT"),nullable=False),sa.Column("policy_decision",sa.JSON,nullable=False),sa.Column("created_at",sa.DateTime,nullable=False),sa.Column("updated_at",sa.DateTime,nullable=False),sa.Column("approved_at",sa.DateTime),sa.Column("executed_at",sa.DateTime),sa.Column("expires_at",sa.DateTime),sa.CheckConstraint("status IN ('PROPOSED','APPROVED','EXECUTING','SUCCEEDED','FAILED','REJECTED','EXPIRED','BLOCKED')",name="action_intent_status"),sa.CheckConstraint("source='PLANNER' OR source LIKE 'ADDON:%'",name="action_intent_source"),sa.CheckConstraint("tier IN ('T0','T1','T2','T3','T4')",name="action_intent_tier"),sa.UniqueConstraint("plan_line_id","action_type",name="uq_action_plan_line_type"))
    op.create_index("ix_kosh_action_intents_seller_status","kosh_action_intents",["seller_id","status"])

def downgrade():op.drop_table("kosh_action_intents")
