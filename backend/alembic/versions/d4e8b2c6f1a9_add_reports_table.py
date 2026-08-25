"""Add reports table (Phase 4, #396).

Column is named `meta`, not `metadata` — the latter is reserved by
SQLAlchemy's declarative API (decision in #232).

Revision ID: d4e8b2c6f1a9
Revises: c1a7f3d9e2b4
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8b2c6f1a9'
down_revision: Union[str, Sequence[str], None] = 'c1a7f3d9e2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_date', name='uq_report_date'),
    )
    op.create_index('idx_reports_report_date', 'reports', ['report_date'])


def downgrade() -> None:
    op.drop_index('idx_reports_report_date', table_name='reports')
    op.drop_table('reports')
