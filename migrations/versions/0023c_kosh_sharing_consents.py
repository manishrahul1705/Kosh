"""Exact-purpose and recipient-scoped outbound sharing consent."""
from alembic import op
import sqlalchemy as sa
revision="0023c_kosh_sharing_consents"
down_revision="0023b_kosh_otp_step_up"
branch_labels=None
depends_on=None
PK=sa.BigInteger().with_variant(sa.Integer(),"sqlite")

def upgrade():
    op.create_table("kosh_sharing_consents",sa.Column("id",PK,primary_key=True),sa.Column("seller_id",PK,sa.ForeignKey("sellers.id",ondelete="RESTRICT"),nullable=False),sa.Column("granted_by_user_id",sa.Integer,sa.ForeignKey("app_users.id",ondelete="RESTRICT"),nullable=False),sa.Column("purpose",sa.String(48),nullable=False),sa.Column("recipient_id",sa.String(64),nullable=False),sa.Column("fields",sa.JSON,nullable=False),sa.Column("expires_at",sa.DateTime,nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("revoked_at",sa.DateTime),sa.Column("created_at",sa.DateTime,nullable=False),sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED')",name="sharing_consent_status"))
    op.create_index("ix_kosh_sharing_consents_seller_id","kosh_sharing_consents",["seller_id"])

def downgrade():op.drop_table("kosh_sharing_consents")
