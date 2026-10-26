"""新增 TAIEX 歷史 OHLC 的開盤、最高與最低欄位。

Revision ID: e8f6c2a91b04
Revises: d3a8b6e15c27
"""

import sqlalchemy as sa
from alembic import op

revision = "e8f6c2a91b04"
down_revision = "d3a8b6e15c27"
branch_labels = None
depends_on = None

_COLUMNS = ("open", "high", "low")


def upgrade():
    # 只新增 nullable 欄位，不重寫既有列；等不到鎖就退出，避免卡住正式 Web 讀取。
    op.execute("SET lock_timeout = '10s'")
    for name in _COLUMNS:
        op.add_column("market_index", sa.Column(name, sa.Numeric(14, 2), nullable=True), schema="market")


def downgrade():
    # market 無備份；已有 OHLC 時拒絕刪欄，退程式可保留新增結構。
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM market.market_index "
        "WHERE open IS NOT NULL OR high IS NOT NULL OR low IS NOT NULL")).scalar()
    if count:
        raise RuntimeError(f"拒絕降版：market_index 仍有 {count:,} 列 OHLC；請先匯出並確認資料處置")
    op.execute("SET lock_timeout = '10s'")
    for name in reversed(_COLUMNS):
        op.drop_column("market_index", name, schema="market")
