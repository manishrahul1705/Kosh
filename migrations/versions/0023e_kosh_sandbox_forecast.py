"""Separately label sandbox cash in forecast weeks."""
from alembic import op
import sqlalchemy as sa
revision="0023e_kosh_sandbox_forecast"
down_revision="0023d_kosh_sandbox_adapters"
branch_labels=None
depends_on=None

def upgrade():
    for name in ("expected_inflow_sandbox_paise","expected_outflow_sandbox_paise"):
        op.add_column("kosh_forecast_weeks",sa.Column(name,sa.BigInteger,nullable=False,server_default="0"))

def downgrade():
    for name in ("expected_outflow_sandbox_paise","expected_inflow_sandbox_paise"):op.drop_column("kosh_forecast_weeks",name)
