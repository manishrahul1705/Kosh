"""Persist plan safety and comparison evidence without altering old migrations."""
from alembic import op
import sqlalchemy as sa
revision="0022a_kosh_plan_safety"
down_revision="0022_kosh_financing"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column("kosh_plans",sa.Column("planning_details",sa.JSON,nullable=False,server_default="{}"))

def downgrade():
    op.drop_column("kosh_plans","planning_details")
