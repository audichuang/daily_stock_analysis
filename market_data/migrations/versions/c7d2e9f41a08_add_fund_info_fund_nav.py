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
    # market schema 是唯一資料源、沒有備份；公會淨值檔每檔只留最新一筆，入庫累積的每日淨值抓不回來
    # （鉅亨只補得到有對照的基金），fund_info.cnyes_id 的 ISIN 對照也要逐檔重查。
    # 兩表都先檢查，任一表有資料就在移除任何索引或資料表前拒絕（同 d3a8b6e15c27 的護欄）。
    bind = op.get_bind()
    row_counts = {
        table: bind.execute(sa.text(f"SELECT count(*) FROM market.{table}")).scalar_one()
        for table in ('fund_info', 'fund_nav')
    }
    if any(row_counts.values()):
        counts = '、'.join(f"{table} {count:,} 列" for table, count in row_counts.items())
        raise RuntimeError(
            f"拒絕降版：{counts}仍在。market schema 無備份，公會歷史淨值無法重抓；"
            "請先匯出兩表並確認備份，再自行清空兩表後重跑 downgrade")
    op.drop_index('ix_fund_nav_date', table_name='fund_nav', schema='market')
    op.drop_table('fund_nav', schema='market')
    op.drop_index('ix_fund_info_isin', table_name='fund_info', schema='market')
    op.drop_table('fund_info', schema='market')
