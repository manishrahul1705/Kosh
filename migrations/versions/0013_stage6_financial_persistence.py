"""Add financial persistence foundation for Stage 6.

Revision ID: 0013_stage6_financial_persistence
Revises: 0012_opportunity_tender_metadata_fingerprint
"""

revision = "0013_stage6_financial_persistence"
down_revision = "0012_opportunity_tender_metadata_fingerprint"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from datetime import date
from decimal import Decimal


def upgrade():
    # Create seller_cost_profiles table
    op.create_table(
        "seller_cost_profiles",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("seller_id", sa.Integer(), nullable=False),
        sa.Column("seller_revision_id", sa.Integer(), nullable=False),
        sa.Column("profile_version", sa.String(length=40), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("procurement", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("raw_materials", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("labor", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("manufacturing", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("packaging", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("freight", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("insurance", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("installation", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("warranty", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("overheads", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("financing", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("contingency", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("variable_cost_per_unit", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), onupdate=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_revision_id"], ["seller_revisions.id"], ondelete="CASCADE"),
        sa.Index("uq_seller_cost_profile_version", "seller_id", "revision_number", "profile_version", unique=True),
        sa.Index("ix_seller_cost_profile_seller", "seller_id"),
        sa.Index("ix_seller_cost_profiles_seller_id", "seller_id"),
        sa.Index("ix_seller_cost_profiles_seller_revision_id", "seller_revision_id"),
    )

    # Create tender_financial_scenarios table
    op.create_table(
        "tender_financial_scenarios",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("seller_id", sa.Integer(), nullable=False),
        sa.Column("scenario_version", sa.String(length=40), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("estimated_value", sa.Numeric(20, 2), nullable=False),
        sa.Column("proposed_bid_revenue", sa.Numeric(20, 2), nullable=True),
        sa.Column("emd_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("performance_security", sa.Numeric(20, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), onupdate=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        sa.Index("uq_tender_financial_scenario", "tender_id", "seller_id", "scenario_version", unique=True),
        sa.Index("ix_tender_financial_scenario_seller", "seller_id"),
        sa.Index("ix_tender_financial_scenarios_seller_id", "seller_id"),
        sa.Index("ix_tender_financial_scenarios_tender_id", "tender_id"),
    )

    # Create tender_cash_flow_events table
    op.create_table(
        "tender_cash_flow_events",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["scenario_id"], ["tender_financial_scenarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE"),
        sa.Index("uq_tender_cash_flow_event_date", "scenario_id", "on_date", "kind", unique=True),
        sa.Index("ix_tender_cash_flow_event_scenario", "scenario_id"),
        sa.Index("ix_tender_cash_flow_events_scenario_id", "scenario_id"),
        sa.Index("ix_tender_cash_flow_events_tender_id", "tender_id"),
    )

    # Create tender_financial_evaluation_snapshots table
    op.create_table(
        "tender_financial_evaluation_snapshots",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("evaluation_version", sa.String(length=40), nullable=False),
        sa.Column("fixed_costs", sa.Text(), nullable=False),
        sa.Column("variable_costs", sa.Text(), nullable=False),
        sa.Column("fulfillment_cost", sa.Numeric(20, 2), nullable=False),
        sa.Column("revenue", sa.Numeric(20, 2), nullable=False),
        sa.Column("gross_profit", sa.Numeric(20, 2), nullable=False),
        sa.Column("net_profit", sa.Numeric(20, 2), nullable=False),
        sa.Column("break_even_price", sa.Numeric(20, 2), nullable=False),
        sa.Column("target_margin_price", sa.Numeric(20, 2), nullable=False),
        sa.Column("working_capital", sa.Numeric(20, 2), nullable=True),
        sa.Column("taxes", sa.Text(), nullable=False),
        sa.Column("deposits", sa.Text(), nullable=False),
        sa.Column("contingency", sa.Numeric(20, 2), nullable=False),
        sa.Column("scenario", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["scenario_id"], ["tender_financial_scenarios.id"], ondelete="CASCADE"),
        sa.Index("uq_tender_financial_evaluation_snapshot", "scenario_id", "evaluation_version", unique=True),
        sa.Index("ix_tender_financial_evaluation_snapshot_scenario", "scenario_id"),
        sa.Index("ix_tender_financial_evaluation_snapshots_scenario_id", "scenario_id"),
    )

    # Create financial_change_audit table
    op.create_table(
        "financial_change_audit",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("scenario_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("change_type", sa.String(length=40), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["scenario_id"], ["tender_financial_scenarios.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["tender_financial_evaluation_snapshots.id"], ondelete="SET NULL"),
        sa.Index("ix_financial_change_audit_scenario", "scenario_id"),
        sa.Index("ix_financial_change_audit_user", "user_id"),
        sa.Index("ix_financial_change_audit_scenario_id", "scenario_id"),
        sa.Index("ix_financial_change_audit_snapshot_id", "snapshot_id"),
    )




def downgrade():
    # Drop financial_change_audit table
    op.drop_table("financial_change_audit")

    # Drop tender_financial_evaluation_snapshots table
    op.drop_table("tender_financial_evaluation_snapshots")

    # Drop tender_cash_flow_events table
    op.drop_table("tender_cash_flow_events")

    # Drop tender_financial_scenarios table
    op.drop_table("tender_financial_scenarios")

    # Drop seller_cost_profiles table
    op.drop_table("seller_cost_profiles")

