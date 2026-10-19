"""Idempotent sandbox execution, ledger and outbox storage."""
from alembic import op
import sqlalchemy as sa
revision="0023d_kosh_sandbox_adapters"
down_revision="0023c_kosh_sharing_consents"
branch_labels=None
depends_on=None
PK=sa.BigInteger().with_variant(sa.Integer(),"sqlite")

def upgrade():
    op.add_column("kosh_policy_controls",sa.Column("sandbox_fail_next",sa.Boolean,nullable=False,server_default=sa.false()))
    op.create_table("kosh_sandbox_executions",sa.Column("id",sa.String(36),primary_key=True),sa.Column("intent_id",sa.String(36),sa.ForeignKey("kosh_action_intents.id",ondelete="RESTRICT"),nullable=False,unique=True),sa.Column("seller_id",PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("idempotency_key",sa.String(128),nullable=False,unique=True),sa.Column("params_hash",sa.CHAR(64),nullable=False),sa.Column("adapter",sa.String(16),nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("expected_entries",sa.JSON,nullable=False),sa.Column("result",sa.JSON,nullable=False),sa.Column("history",sa.JSON,nullable=False),sa.Column("error",sa.Text),sa.Column("created_at",sa.DateTime,nullable=False),sa.Column("updated_at",sa.DateTime,nullable=False),sa.CheckConstraint("status IN ('PENDING','SUBMITTED','SETTLED','FAILED')",name="sandbox_execution_status"))
    op.create_table("kosh_sandbox_ledger",sa.Column("id",PK,primary_key=True),sa.Column("execution_id",sa.String(36),sa.ForeignKey("kosh_sandbox_executions.id",ondelete="RESTRICT"),nullable=False),sa.Column("seller_id",PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("entry_key",sa.String(48),nullable=False),sa.Column("entry_date",sa.Date,nullable=False),sa.Column("amount_paise",sa.BigInteger,nullable=False),sa.Column("kind",sa.String(32),nullable=False),sa.Column("invoice_id",PK,sa.ForeignKey("kosh_invoices.id",ondelete="RESTRICT")),sa.Column("receivable_reduction_paise",sa.BigInteger,nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("label",sa.String(16),nullable=False),sa.Column("posted_at",sa.DateTime,nullable=False),sa.UniqueConstraint("execution_id","entry_key",name="uq_sandbox_execution_entry"),sa.CheckConstraint("label='SANDBOX'",name="sandbox_ledger_label"),sa.CheckConstraint("status IN ('POSTED','SCHEDULED')",name="sandbox_ledger_status"))
    op.create_table("kosh_sandbox_outbox",sa.Column("id",sa.String(36),primary_key=True),sa.Column("seller_id",PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("execution_id",sa.String(36),sa.ForeignKey("kosh_sandbox_executions.id",ondelete="RESTRICT"),nullable=False,unique=True),sa.Column("intent_id",sa.String(36),sa.ForeignKey("kosh_action_intents.id",ondelete="RESTRICT"),nullable=False),sa.Column("channel",sa.String(16),nullable=False),sa.Column("recipient_ref",sa.String(128),nullable=False),sa.Column("body",sa.Text,nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("created_at",sa.DateTime,nullable=False))

def downgrade():
    op.drop_table("kosh_sandbox_outbox");op.drop_table("kosh_sandbox_ledger");op.drop_table("kosh_sandbox_executions");op.drop_column("kosh_policy_controls","sandbox_fail_next")
