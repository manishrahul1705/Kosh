"""Label optional revenue forecast cash separately."""
from alembic import op
import sqlalchemy as sa
revision="0024c_kosh_revenue_signal"
down_revision="0024b_kosh_operations"
branch_labels=None
depends_on=None
def upgrade():op.add_column("kosh_forecast_weeks",sa.Column("expected_inflow_revenue_paise",sa.BigInteger,nullable=False,server_default="0"))
def downgrade():op.drop_column("kosh_forecast_weeks","expected_inflow_revenue_paise")
