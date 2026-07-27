"""Add ML models, predictions, and metrics tables

Revision ID: 2b05965fde4e
Revises: 055f1bb767f3
Create Date: 2026-07-27 07:15:59.170971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b05965fde4e'
down_revision: Union[str, Sequence[str], None] = '055f1bb767f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema using batch mode for SQLite compatibility."""
    
    # Update model_metrics table
    with op.batch_alter_table('model_metrics', schema=None) as batch_op:
        # Add new columns
        batch_op.add_column(sa.Column('date', sa.Date(), nullable=False, server_default='2026-01-01'))
        batch_op.add_column(sa.Column('brier_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('f1_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('f2_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('precision_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('recall', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('calibration_slope', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('threshold', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('confusion_matrix', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
        
        # Drop old columns
        batch_op.drop_column('metric_name')
        batch_op.drop_column('evaluation_date')
        batch_op.drop_column('dataset_info')
        batch_op.drop_column('metric_value')
        
        # Update indexes
        batch_op.drop_index('ix_model_metrics_id')
        batch_op.create_index(batch_op.f('ix_model_metrics_date'), ['date'], unique=False)
        batch_op.create_index(batch_op.f('ix_model_metrics_model_id'), ['model_id'], unique=False)
        batch_op.create_unique_constraint('uq_model_date', ['model_id', 'date'])
    
    # Remove server_default after table creation
    with op.batch_alter_table('model_metrics', schema=None) as batch_op:
        batch_op.alter_column('date', server_default=None)
        batch_op.alter_column('created_at', server_default=None)
    
    # Update models table
    with op.batch_alter_table('models', schema=None) as batch_op:
        # Add new columns
        batch_op.add_column(sa.Column('description', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('active', sa.Boolean(), nullable=True, server_default='1'))
        
        # Alter existing columns
        batch_op.alter_column('version', existing_type=sa.VARCHAR(), nullable=True)
        batch_op.alter_column('config', existing_type=sa.TEXT(), type_=sa.JSON(), existing_nullable=True)
        batch_op.alter_column('created_at', existing_type=sa.DATETIME(), nullable=False)
        
        # Update indexes
        batch_op.drop_index('ix_models_id')
        batch_op.drop_index('ix_models_name')
        batch_op.create_index(batch_op.f('ix_models_name'), ['name'], unique=True)
        batch_op.create_index(batch_op.f('ix_models_active'), ['active'], unique=False)
    
    # Remove server_default after table creation
    with op.batch_alter_table('models', schema=None) as batch_op:
        batch_op.alter_column('active', server_default=None)
    
    # Update predictions table
    with op.batch_alter_table('predictions', schema=None) as batch_op:
        # Add new columns
        batch_op.add_column(sa.Column('probability', sa.Float(), nullable=False, server_default='0.0'))
        batch_op.add_column(sa.Column('threshold', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('binary_prediction', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
        
        # Drop old columns
        batch_op.drop_column('confidence')
        batch_op.drop_column('prediction')
        batch_op.drop_column('input_data')
        
        # Update indexes
        batch_op.drop_index('idx_predictions_model_id')
        batch_op.drop_index('idx_predictions_timestamp')
        batch_op.drop_index('ix_predictions_id')
        batch_op.create_index(batch_op.f('ix_predictions_model_id'), ['model_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_predictions_timestamp'), ['timestamp'], unique=False)
        batch_op.create_unique_constraint('uq_model_timestamp', ['model_id', 'timestamp'])
    
    # Remove server_default after table creation
    with op.batch_alter_table('predictions', schema=None) as batch_op:
        batch_op.alter_column('probability', server_default=None)
        batch_op.alter_column('created_at', server_default=None)


def downgrade() -> None:
    """Downgrade schema using batch mode for SQLite compatibility."""
    
    # Revert predictions table
    with op.batch_alter_table('predictions', schema=None) as batch_op:
        # Add old columns back
        batch_op.add_column(sa.Column('input_data', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('prediction', sa.TEXT(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('confidence', sa.FLOAT(), nullable=True))
        
        # Drop new columns
        batch_op.drop_column('created_at')
        batch_op.drop_column('binary_prediction')
        batch_op.drop_column('threshold')
        batch_op.drop_column('probability')
        
        # Restore indexes
        batch_op.drop_constraint('uq_model_timestamp', type_='unique')
        batch_op.drop_index(batch_op.f('ix_predictions_timestamp'))
        batch_op.drop_index(batch_op.f('ix_predictions_model_id'))
        batch_op.create_index('ix_predictions_id', ['id'], unique=False)
        batch_op.create_index('idx_predictions_timestamp', ['timestamp'], unique=False)
        batch_op.create_index('idx_predictions_model_id', ['model_id'], unique=False)
    
    # Remove server_default
    with op.batch_alter_table('predictions', schema=None) as batch_op:
        batch_op.alter_column('prediction', server_default=None)
    
    # Revert models table
    with op.batch_alter_table('models', schema=None) as batch_op:
        # Restore indexes
        batch_op.drop_index(batch_op.f('ix_models_active'))
        batch_op.drop_index(batch_op.f('ix_models_name'))
        batch_op.create_index('ix_models_name', ['name'], unique=False)
        batch_op.create_index('ix_models_id', ['id'], unique=False)
        
        # Alter columns back
        batch_op.alter_column('created_at', existing_type=sa.DATETIME(), nullable=True)
        batch_op.alter_column('config', existing_type=sa.JSON(), type_=sa.TEXT(), existing_nullable=True)
        batch_op.alter_column('version', existing_type=sa.VARCHAR(), nullable=False, server_default='1.0')
        
        # Drop new columns
        batch_op.drop_column('active')
        batch_op.drop_column('description')
    
    # Remove server_default
    with op.batch_alter_table('models', schema=None) as batch_op:
        batch_op.alter_column('version', server_default=None)
    
    # Revert model_metrics table
    with op.batch_alter_table('model_metrics', schema=None) as batch_op:
        # Add old columns back
        batch_op.add_column(sa.Column('metric_value', sa.FLOAT(), nullable=False, server_default='0.0'))
        batch_op.add_column(sa.Column('dataset_info', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('evaluation_date', sa.DATETIME(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')))
        batch_op.add_column(sa.Column('metric_name', sa.VARCHAR(), nullable=False, server_default='unknown'))
        
        # Drop new columns
        batch_op.drop_column('created_at')
        batch_op.drop_column('confusion_matrix')
        batch_op.drop_column('threshold')
        batch_op.drop_column('calibration_slope')
        batch_op.drop_column('recall')
        batch_op.drop_column('precision_score')
        batch_op.drop_column('f2_score')
        batch_op.drop_column('f1_score')
        batch_op.drop_column('brier_score')
        batch_op.drop_column('date')
        
        # Restore indexes
        batch_op.drop_constraint('uq_model_date', type_='unique')
        batch_op.drop_index(batch_op.f('ix_model_metrics_model_id'))
        batch_op.drop_index(batch_op.f('ix_model_metrics_date'))
        batch_op.create_index('ix_model_metrics_id', ['id'], unique=False)
    
    # Remove server_defaults
    with op.batch_alter_table('model_metrics', schema=None) as batch_op:
        batch_op.alter_column('metric_value', server_default=None)
        batch_op.alter_column('evaluation_date', server_default=None)
        batch_op.alter_column('metric_name', server_default=None)
