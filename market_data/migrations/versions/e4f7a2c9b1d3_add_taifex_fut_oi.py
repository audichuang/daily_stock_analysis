"""add taifex_fut_oi (期交所三大法人臺股期貨未平倉，每日累積)

Revision ID: e4f7a2c9b1d3
Revises: d3a8b6e15c27
Create Date: 2026-10-26 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e4f7a2c9b1d3'
down_revision: Union[str, None] = 'd3a8b6e15c27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'taifex_fut_oi',
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('commodity_id', sa.String(length=8), nullable=False),
        sa.Column('identity', sa.String(length=8), nullable=False),
        sa.Column('long_oi', sa.BigInteger(), nullable=True),
        sa.Column('short_oi', sa.BigInteger(), nullable=True),
        sa.Column('net_oi', sa.BigInteger(), nullable=True),
        sa.Column('long_oi_amount', sa.BigInteger(), nullable=True),
        sa.Column('short_oi_amount', sa.BigInteger(), nullable=True),
        sa.Column('net_oi_amount', sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint('date', 'commodity_id', 'identity'),
        schema='market',
    )


def downgrade() -> None:
    # market schema 是唯一資料源、沒有備份；期交所每次只查得到近期窗口，入庫累積的每日未平倉
    # 拿不回來。表裡有資料就在刪表前拒絕（同 c7d2e9f41a08／d3a8b6e15c27 的護欄）：先匯出、
    # 確認備份，再自行 TRUNCATE market.taifex_fut_oi 後重跑 downgrade。
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT count(*) FROM market.taifex_fut_oi")).scalar_one()
    if rows:
        raise RuntimeError(
            f"拒絕降版：taifex_fut_oi {rows:,} 列仍在。market schema 無備份，期交所歷史未平倉無法重抓；"
            "請先匯出並確認備份，再 TRUNCATE market.taifex_fut_oi 後重跑 downgrade")
    op.drop_table('taifex_fut_oi', schema='market')
