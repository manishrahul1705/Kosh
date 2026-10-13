"""Stage 5: Opportunity Scoring & Ranking Engine"""

from alembic import op
import sqlalchemy as sa

revision = '0010_stage5_opportunity_scoring'
down_revision = '0009_eligibility_ai_analysis_identity'
branch_labels = None
depends_on = None


def upgrade():
    # Create opportunity_score_runs table
    op.create_table(
        'opportunity_score_runs',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), primary_key=True, autoincrement=True),
        sa.Column('tender_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('seller_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('seller_revision_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('corpus_fingerprint', sa.String(64), nullable=False),
        sa.Column('scoring_model_version', sa.String(40), nullable=False),
        sa.Column('scoring_config_fingerprint', sa.String(64), nullable=False),
        sa.Column('eligibility_run_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('action_category', sa.String(40), nullable=False),
        sa.Column('eligibility_status', sa.String(40), nullable=False),
        sa.Column('overall_score', sa.Float(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('evaluated_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tender_id'], ['tenders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['seller_id'], ['sellers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['seller_revision_id'], ['seller_revisions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['eligibility_run_id'], ['eligibility_runs.id'], ondelete='SET NULL'),
        sa.Index('ix_opportunity_score_runs_tender_seller', 'tender_id', 'seller_id'),
        sa.Index('uq_opportunity_score_run_version', 'tender_id', 'seller_revision_id', 'corpus_fingerprint', 'scoring_model_version', 'scoring_config_fingerprint', 'eligibility_run_id', unique=True)
    )

    # Create opportunity_score_dimensions table
    op.create_table(
        'opportunity_score_dimensions',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), primary_key=True, autoincrement=True),
        sa.Column('run_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('dimension', sa.String(40), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False),
        sa.Column('raw_score', sa.Float(), nullable=False),
        sa.Column('normalized_score', sa.Float(), nullable=False),
        sa.Column('completeness', sa.Float(), nullable=False),
        sa.Column('actionable', sa.Boolean(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['opportunity_score_runs.id'], ondelete='CASCADE'),
        sa.Index('ix_opportunity_score_dimensions_run_id', 'run_id')
    )

    # Create opportunity_evidence table
    op.create_table(
        'opportunity_evidence',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), primary_key=True, autoincrement=True),
        sa.Column('dimension_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('tender_field_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('ai_requirement_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('document_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('seller_attribute_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('seller_document_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
        sa.Column('evidence_value', sa.Text(), nullable=True),
        sa.Column('evidence_type', sa.String(40), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['dimension_id'], ['opportunity_score_dimensions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tender_field_id'], ['tender_field_values.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ai_requirement_id'], ['ai_requirements.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['document_id'], ['tender_documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['seller_attribute_id'], ['seller_attributes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['seller_document_id'], ['seller_documents.id'], ondelete='SET NULL'),
        sa.Index('ix_opportunity_evidence_dimension_id', 'dimension_id')
    )

    # Create scoring_configurations table
    op.create_table(
        'scoring_configurations',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), primary_key=True, autoincrement=True),
        sa.Column('model_version', sa.String(40), nullable=False),
        sa.Column('config_fingerprint', sa.String(64), nullable=False),
        sa.Column('config_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Index('uq_scoring_configuration_version', 'model_version', 'config_fingerprint', unique=True)
    )

def downgrade():
    op.drop_table('opportunity_evidence')
    op.drop_table('opportunity_score_dimensions')
    op.drop_table('opportunity_score_runs')
    op.drop_table('scoring_configurations')
