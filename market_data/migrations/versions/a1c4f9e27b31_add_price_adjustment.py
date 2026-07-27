"""add price_adjustment (前復權因子:除權息/分割/減資)

Revision ID: a1c4f9e27b31
Revises: 63245ce65067
Create Date: 2026-07-26 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1c4f9e27b31'
down_revision: Union[str, None] = '63245ce65067'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'price_adjustment',
        sa.Column('stock_id', sa.String(length=12), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('factor', sa.Numeric(precision=18, scale=10), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('source', sa.String(length=24), nullable=False),
        sa.Column('close_before', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('reference_price', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.PrimaryKeyConstraint('stock_id', 'date'),
        schema='market',
    )
    op.create_index('ix_price_adjustment_date', 'price_adjustment', ['date'], schema='market')


def downgrade() -> None:
    op.drop_index('ix_price_adjustment_date', table_name='price_adjustment', schema='market')
    op.drop_table('price_adjustment', schema='market')
