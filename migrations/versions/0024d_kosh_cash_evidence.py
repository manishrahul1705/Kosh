"""Prevent duplicate cash proposals for the same scoped evidence."""
from alembic import op
revision="0024d_kosh_cash_evidence"
down_revision="0024c_kosh_revenue_signal"
branch_labels=None
depends_on=None
def upgrade():
    with op.batch_alter_table('kosh_cash_events') as batch:batch.create_unique_constraint('uq_cash_event_evidence',['seller_id','source_module','event_type','evidence_ref'])
def downgrade():
    with op.batch_alter_table('kosh_cash_events') as batch:batch.drop_constraint('uq_cash_event_evidence',type_='unique')
