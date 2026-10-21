"""add fund_info, fund_nav (境內基金基本資料與每日淨值)

Revision ID: c7d2e9f41a08
Revises: a1c4f9e27b31
Create Date: 2026-10-21 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c7d2e9f41a08'
down_revision: Union[str, None] = 'a1c4f9e27b31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fund_info',
        sa.Column('fund_id', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('company', sa.String(length=32), nullable=True),
        sa.Column('isin', sa.String(length=16), nullable=True),
        sa.Column('sitca_code', sa.String(length=16), nullable=True),
        sa.Column('type_code', sa.String(length=8), nullable=True),
        sa.Column('type_name', sa.String(length=64), nullable=True),
        sa.Column('invest_area', sa.String(length=128), nullable=True),
        sa.Column('currency', sa.String(length=8), nullable=True),
        sa.Column('inception_date', sa.Date(), nullable=True),
        sa.Column('aum', sa.BigInteger(), nullable=True),
        sa.Column('aum_currency', sa.String(length=8), nullable=True),
        sa.Column('aum_date', sa.Date(), nullable=True),
        sa.Column('dividend_policy', sa.String(length=128), nullable=True),
        sa.Column('cnyes_id', sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint('fund_id'),
        schema='market',
    )
    op.create_index('ix_fund_info_isin', 'fund_info', ['isin'], schema='market')
    op.create_table(
        'fund_nav',
        sa.Column('fund_id', sa.String(length=16), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('nav', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('change', sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column('change_pct', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('source', sa.String(length=8), nullable=False),
        sa.PrimaryKeyConstraint('fund_id', 'date'),
        schema='market',
    )
    op.create_index('ix_fund_nav_date', 'fund_nav', ['date'], schema='market')


def downgrade() -> None:
    op.drop_index('ix_fund_nav_date', table_name='fund_nav', schema='market')
    op.drop_table('fund_nav', schema='market')
    op.drop_index('ix_fund_info_isin', table_name='fund_info', schema='market')
    op.drop_table('fund_info', schema='market')
