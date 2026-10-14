"""Owner-controlled native module flags; default enabled when absent."""
from alembic import op
import sqlalchemy as sa
revision="0025_kosh_module_flags"
down_revision="0024d_kosh_cash_evidence"
branch_labels=None
depends_on=None
def upgrade():op.create_table('kosh_module_flags',sa.Column('seller_id',sa.Integer,sa.ForeignKey('sellers.id',ondelete='RESTRICT'),primary_key=True),sa.Column('module',sa.String(48),primary_key=True),sa.Column('enabled',sa.Boolean,nullable=False),sa.Column('updated_at',sa.DateTime,nullable=False))
def downgrade():op.drop_table('kosh_module_flags')
