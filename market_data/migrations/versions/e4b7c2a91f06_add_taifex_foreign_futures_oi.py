"""新增期交所外資大台 TXF 淨未平倉累積表。

Revision ID: e4b7c2a91f06
Revises: d3a8b6e15c27
"""

import sqlalchemy as sa
from alembic import op

revision = "e4b7c2a91f06"
down_revision = "d3a8b6e15c27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taifex_foreign_futures_oi",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("foreign_fut_oi", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("date"),
        schema="market",
    )


def downgrade() -> None:
    # 歷史只靠逐日累積；非空時在任何 DDL 之前拒絕，避免唯一資料源被刪除。
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM market.taifex_foreign_futures_oi"
    )).scalar_one()
    if count:
        raise RuntimeError(
            f"拒絕降版：taifex_foreign_futures_oi 仍有 {count:,} 列。market schema 無備份；"
            "請先匯出並確認備份，再自行清空資料表後重跑 downgrade")
    op.drop_table("taifex_foreign_futures_oi", schema="market")
