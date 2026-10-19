"""Nullable evidence fields for owner collection terms."""
from alembic import op
import sqlalchemy as sa

revision = "0026_kosh_collection_evidence"
down_revision = "0025_kosh_module_flags"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("kosh_collection_terms") as batch:
        batch.alter_column("acceptance_date", existing_type=sa.Date(), nullable=True)
        batch.alter_column("supplier_mse", existing_type=sa.Boolean(), nullable=True)
        batch.alter_column("evidence_ref", existing_type=sa.String(160), nullable=True)

def downgrade():
    with op.batch_alter_table("kosh_collection_terms") as batch:
        batch.alter_column("evidence_ref", existing_type=sa.String(160), nullable=False)
        batch.alter_column("supplier_mse", existing_type=sa.Boolean(), nullable=False)
        batch.alter_column("acceptance_date", existing_type=sa.Date(), nullable=False)

