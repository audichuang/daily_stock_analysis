"""add macro_series, rate_expectations, event_calendar (總經日線、Fed 利率預期、重大事件)

Revision ID: f2a7c4d8e913
Revises: e8f6c2a91b04
Create Date: 2026-10-26 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f2a7c4d8e913'
down_revision: Union[str, None] = 'e8f6c2a91b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('macro_series', 'rate_expectations', 'event_calendar')


def upgrade() -> None:
    op.create_table(
        'macro_series',
        sa.Column('series_id', sa.String(length=24), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('value', sa.Numeric(18, 6), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('series_id', 'date'),
        schema='market',
    )
    op.create_table(
        'rate_expectations',
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('meeting_date', sa.Date(), nullable=False),
        sa.Column('outcome', sa.String(length=12), nullable=False),
        sa.Column('prob_mid', sa.Numeric(6, 4), nullable=True),
        sa.Column('yes_bid', sa.Numeric(6, 4), nullable=True),
        sa.Column('yes_ask', sa.Numeric(6, 4), nullable=True),
        sa.Column('last_price', sa.Numeric(6, 4), nullable=True),
        sa.Column('volume', sa.Numeric(18, 2), nullable=True),
        sa.Column('open_interest', sa.Numeric(18, 2), nullable=True),
        sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint('snapshot_date', 'meeting_date', 'outcome'),
        schema='market',
    )
    op.create_table(
        'event_calendar',
        sa.Column('event_type', sa.String(length=16), nullable=False),
        sa.Column('symbol', sa.String(length=16), nullable=False),
        sa.Column('label', sa.String(length=16), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=True),
        sa.Column('title', sa.String(length=128), nullable=True),
        sa.Column('time_note', sa.String(length=64), nullable=True),
        sa.Column('source', sa.String(length=24), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('event_type', 'symbol', 'label'),
        schema='market',
    )


def downgrade() -> None:
    # 利率預期快照只有當天抓得到（Kalshi 不給歷史快照），丟了就拿不回來；表裡有資料就拒絕，
    # 同 e4f7a2c9b1d3 的護欄：先匯出確認備份，再自行 TRUNCATE 後重跑 downgrade。
    bind = op.get_bind()
    for table in _TABLES:
        rows = bind.execute(sa.text(f"SELECT count(*) FROM market.{table}")).scalar_one()
        if rows:
            raise RuntimeError(
                f"拒絕降版：{table} {rows:,} 列仍在。market schema 無備份；"
                f"請先匯出並確認備份，再 TRUNCATE market.{table} 後重跑 downgrade")
    for table in reversed(_TABLES):
        op.drop_table(table, schema='market')
