"""add release fields to event_calendar (公布時刻、首發實際值與前值、vintage)

Revision ID: a6c1e3f5b7d9
Revises: f2a7c4d8e913
Create Date: 2026-10-27 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a6c1e3f5b7d9'
down_revision: Union[str, None] = 'f2a7c4d8e913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 全部可空：FOMC、財報舊列維持 NULL
_COLUMNS = (
    ('released_at', sa.DateTime(timezone=True)),
    ('series_id', sa.String(length=24)),
    ('observation_date', sa.Date()),
    ('actual_value', sa.Numeric(18, 6)),
    ('prior_value', sa.Numeric(18, 6)),
    ('actual_vintage', sa.Date()),
    ('actual_source', sa.String(length=16)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column('event_calendar', sa.Column(name, type_, nullable=True), schema='market')


def downgrade() -> None:
    # 首發值是 ALFRED 當時的 vintage（公布日釘住），事後補抓不一定拿得回同一個值；
    # 有任何帶 released_at 的列就拒絕降版（在任何 DDL 之前），同 f2a7c4d8e913 的護欄：
    # 先匯出確認備份，再清掉這些列的新欄位資料後重跑 downgrade。
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT count(*) FROM market.event_calendar WHERE released_at IS NOT NULL")).scalar_one()
    if rows:
        raise RuntimeError(
            f"拒絕降版：event_calendar 有 {rows:,} 列帶 released_at／首發值。market schema 無備份；"
            "請先匯出並確認備份，再 DELETE 這些列（WHERE released_at IS NOT NULL）後重跑 downgrade")
    for name, _ in reversed(_COLUMNS):
        op.drop_column('event_calendar', name, schema='market')
