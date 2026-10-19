"""Trusted native drafts and documented collections terms."""
from alembic import op
import sqlalchemy as sa
revision="0024a_kosh_addon_drafts"
down_revision="0024_kosh_cash_events"
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table("kosh_action_intents") as batch:batch.alter_column("plan_line_id",existing_type=sa.Integer(),nullable=True)
    op.create_table("kosh_addon_drafts",sa.Column("id",sa.Integer,primary_key=True),sa.Column("seller_id",sa.Integer,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("module",sa.String(48),nullable=False),sa.Column("kind",sa.String(48),nullable=False),sa.Column("params",sa.JSON,nullable=False),sa.Column("body",sa.Text,nullable=False),sa.Column("evidence_hash",sa.CHAR(64),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("created_by_user_id",sa.Integer,sa.ForeignKey("app_users.id"),nullable=False),sa.Column("created_at",sa.DateTime,nullable=False))
    op.create_index("ix_kosh_addon_drafts_seller_id","kosh_addon_drafts",["seller_id"])
    op.create_table("kosh_collection_terms",sa.Column("invoice_id",sa.Integer,sa.ForeignKey("kosh_invoices.id",ondelete="RESTRICT"),primary_key=True),sa.Column("seller_id",sa.Integer,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("acceptance_date",sa.Date,nullable=False),sa.Column("agreement_status",sa.String(16),nullable=False),sa.Column("agreed_days",sa.Integer),sa.Column("supplier_mse",sa.Boolean,nullable=False),sa.Column("evidence_ref",sa.String(160),nullable=False))

def downgrade():
    op.drop_table("kosh_collection_terms");op.drop_table("kosh_addon_drafts")
    # Native intents cannot fit the old mandatory plan-line schema.
    connection=op.get_bind()
    if connection.execute(sa.text("SELECT count(*) FROM kosh_action_intents WHERE plan_line_id IS NULL")).scalar():raise RuntimeError("Native intents must be archived before downgrade")
    with op.batch_alter_table("kosh_action_intents") as batch:batch.alter_column("plan_line_id",existing_type=sa.Integer(),nullable=False)
