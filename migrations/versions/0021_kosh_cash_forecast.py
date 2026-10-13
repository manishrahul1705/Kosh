"""Add Kosh cash forecast, alert and backtest storage."""
from alembic import op
import sqlalchemy as sa

revision = "0021_kosh_cash_forecast"
down_revision = "0020_kosh_private_intake"
branch_labels = None
depends_on = None
PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table("kosh_forecast_runs", sa.Column("id", PK, primary_key=True, autoincrement=True), sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False), sa.Column("as_of_date", sa.Date, nullable=False), sa.Column("horizon_weeks", sa.Integer, nullable=False), sa.Column("n_paths", sa.Integer, nullable=False), sa.Column("seed", sa.Integer, nullable=False), sa.Column("params", sa.JSON, nullable=False), sa.Column("input_fingerprint", sa.CHAR(64), nullable=False), sa.Column("include_forecast_sales", sa.Boolean, nullable=False), sa.Column("buffer_paise", sa.BigInteger, nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("created_by_user_id", sa.Integer, sa.ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False), sa.Column("created_at", sa.DateTime, nullable=False), sa.CheckConstraint("status IN ('RUNNING', 'SUCCESS', 'FAILED')", name="forecast_run_status"))
    op.create_index("ix_kosh_forecast_runs_seller_created", "kosh_forecast_runs", ["seller_id", "created_at"])
    op.create_table("kosh_forecast_weeks", sa.Column("id", PK, primary_key=True, autoincrement=True), sa.Column("run_id", PK, sa.ForeignKey("kosh_forecast_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("week_index", sa.Integer, nullable=False), sa.Column("week_start", sa.Date, nullable=False), sa.Column("week_end", sa.Date, nullable=False), sa.Column("p10_closing_balance_paise", sa.BigInteger, nullable=False), sa.Column("p50_closing_balance_paise", sa.BigInteger, nullable=False), sa.Column("p90_closing_balance_paise", sa.BigInteger, nullable=False), sa.Column("expected_inflow_committed_paise", sa.BigInteger, nullable=False), sa.Column("expected_inflow_forecast_paise", sa.BigInteger, nullable=False), sa.Column("expected_outflow_committed_paise", sa.BigInteger, nullable=False), sa.Column("expected_outflow_forecast_paise", sa.BigInteger, nullable=False), sa.Column("prob_below_buffer", sa.Float, nullable=False), sa.Column("expected_shortfall_paise", sa.BigInteger, nullable=False), sa.UniqueConstraint("run_id", "week_index", name="uq_kosh_forecast_week"))
    op.create_index("ix_kosh_forecast_weeks_run_id", "kosh_forecast_weeks", ["run_id"])
    op.create_table("kosh_alerts", sa.Column("id", PK, primary_key=True, autoincrement=True), sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False), sa.Column("run_id", PK, sa.ForeignKey("kosh_forecast_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("week_index", sa.Integer, nullable=False), sa.Column("probability", sa.Float, nullable=False), sa.Column("expected_shortfall_paise", sa.BigInteger, nullable=False), sa.Column("peak_expected_shortfall_paise", sa.BigInteger, nullable=False), sa.Column("causes", sa.JSON, nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime, nullable=False), sa.Column("acknowledged_by", sa.Integer, sa.ForeignKey("app_users.id", ondelete="SET NULL")), sa.Column("acknowledged_at", sa.DateTime), sa.CheckConstraint("status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'SUPERSEDED')", name="kosh_alert_status"))
    op.create_index("ix_kosh_alerts_seller_status", "kosh_alerts", ["seller_id", "status"])
    op.create_table("kosh_backtests", sa.Column("id", PK, primary_key=True, autoincrement=True), sa.Column("seller_id", PK, sa.ForeignKey("sellers.id", ondelete="RESTRICT"), nullable=False), sa.Column("as_of_date", sa.Date, nullable=False), sa.Column("windows", sa.JSON, nullable=False), sa.Column("coverage_by_horizon", sa.JSON, nullable=False), sa.Column("mape_p50_inflow", sa.Float, nullable=False), sa.Column("created_at", sa.DateTime, nullable=False))
    op.create_index("ix_kosh_backtests_seller_created", "kosh_backtests", ["seller_id", "created_at"])


def downgrade() -> None:
    op.drop_table("kosh_backtests")
    op.drop_table("kosh_alerts")
    op.drop_table("kosh_forecast_weeks")
    op.drop_table("kosh_forecast_runs")
