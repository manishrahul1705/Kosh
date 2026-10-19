"""Owner-confirmed cash events and distinct forecast component."""
from alembic import op
import sqlalchemy as sa
revision="0024_kosh_cash_events"
down_revision="0023e_kosh_sandbox_forecast"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("kosh_cash_events",sa.Column("id",sa.Integer,primary_key=True),sa.Column("seller_id",sa.Integer,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("event_type",sa.String(32),nullable=False),sa.Column("source_module",sa.String(48),nullable=False),sa.Column("evidence_ref",sa.String(160),nullable=False),sa.Column("event_date",sa.Date,nullable=False),sa.Column("amount_paise",sa.BigInteger,nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("created_by_user_id",sa.Integer,sa.ForeignKey("app_users.id"),nullable=False),sa.Column("confirmed_by_user_id",sa.Integer,sa.ForeignKey("app_users.id")),sa.Column("created_at",sa.DateTime,nullable=False),sa.Column("confirmed_at",sa.DateTime),sa.CheckConstraint("amount_paise>=0",name="cash_event_amount"),sa.CheckConstraint("status IN ('PROPOSED','CONFIRMED','REJECTED')",name="cash_event_status"),sa.CheckConstraint("event_type IN ('EXPECTED_RECEIVABLE','SCHEDULED_PAYABLE','COST_CHANGE','FINANCING_NEED')",name="cash_event_type"))
    op.create_index("ix_kosh_cash_events_seller_id","kosh_cash_events",["seller_id"])
    for name in ("expected_inflow_addon_paise","expected_outflow_addon_paise"):op.add_column("kosh_forecast_weeks",sa.Column(name,sa.BigInteger,nullable=False,server_default="0"))

def downgrade():
    for name in ("expected_outflow_addon_paise","expected_inflow_addon_paise"):op.drop_column("kosh_forecast_weeks",name)
    op.drop_table("kosh_cash_events")
