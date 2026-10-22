"""add market column to institutional/margin/valuation (上櫃) + holding_dist (集保股權分散)

Revision ID: d3a8b6e15c27
Revises: c7d2e9f41a08
Create Date: 2026-10-22 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd3a8b6e15c27'
down_revision: Union[str, None] = 'c7d2e9f41a08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHIP_TABLES = ('institutional', 'margin', 'valuation')


def upgrade() -> None:
    # ADD COLUMN 要拿 ACCESS EXCLUSIVE 鎖；NAS Web 也在讀這幾張表，排在長查詢後面會把
    # 後續讀取全卡住——等不到鎖就直接失敗，換個安靜時段重跑。
    op.execute("SET lock_timeout = '10s'")
    # nullable、無預設值：既有上市列維持 NULL，只是加欄（不重寫整表）
    for table in _CHIP_TABLES:
        op.add_column(table, sa.Column('market', sa.String(length=8), nullable=True),
                      schema='market')
    op.create_table(
        'holding_dist',
        sa.Column('stock_id', sa.String(length=12), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('holders', sa.Integer(), nullable=True),
        sa.Column('shares', sa.BigInteger(), nullable=True),
        sa.Column('pct', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.PrimaryKeyConstraint('stock_id', 'date', 'level'),
        schema='market',
    )
    # crawl_holding_dist 每天按日期數列判斷該週是否已齊
    op.create_index('ix_holding_dist_date', 'holding_dist', ['date'], schema='market')


def downgrade() -> None:
    # market schema 是唯一資料源、沒有備份；集保超過約 51 週的歷史抓不回來。所以表裡有資料就
    # 拒絕降版，要人工先決定：匯出 holding_dist、刪掉上櫃列（DELETE … WHERE market='tpex'），
    # 清空之後再跑 downgrade。上櫃列不刪就拿掉欄位，會跟上市列混在一起把舊程式的稽核與宇宙灌水。
    bind = op.get_bind()
    tpex = sum(bind.execute(sa.text(f"SELECT count(*) FROM market.{t} WHERE market = 'tpex'")).scalar()
               for t in _CHIP_TABLES)
    holding = bind.execute(sa.text("SELECT count(*) FROM market.holding_dist")).scalar()
    if tpex or holding:
        raise RuntimeError(
            f"拒絕降版：上櫃列 {tpex:,}、holding_dist {holding:,} 列仍在。先匯出 holding_dist，"
            "再 DELETE FROM market.<institutional|margin|valuation> WHERE market='tpex' 與 "
            "TRUNCATE market.holding_dist，確認後重跑 downgrade")
    op.drop_index('ix_holding_dist_date', table_name='holding_dist', schema='market')
    op.drop_table('holding_dist', schema='market')
    for table in _CHIP_TABLES:
        op.drop_column(table, 'market', schema='market')
