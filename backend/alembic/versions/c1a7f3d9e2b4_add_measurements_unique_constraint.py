"""Add unique constraint on measurements (sensor_id, timestamp).

Required for idempotent ingest upserts (INSERT ... ON CONFLICT DO UPDATE).

Revision ID: c1a7f3d9e2b4
Revises: 2b05965fde4e
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c1a7f3d9e2b4'
down_revision: Union[str, Sequence[str], None] = '2b05965fde4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('measurements', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_measurement_sensor_ts', ['sensor_id', 'timestamp']
        )


def downgrade() -> None:
    with op.batch_alter_table('measurements', schema=None) as batch_op:
        batch_op.drop_constraint('uq_measurement_sensor_ts', type_='unique')
