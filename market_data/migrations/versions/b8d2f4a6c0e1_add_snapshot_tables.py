"""snapshots：rate_expectations 加 snapshot_slot（改 PK）、macro_series_snapshot、
institutional_initial、monthly_revenue_first_seen、taifex_fut_oi 加 first_seen_at／captured_at

Revision ID: b8d2f4a6c0e1
Revises: a6c1e3f5b7d9
Create Date: 2026-10-27 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8d2f4a6c0e1'
down_revision: Union[str, None] = 'a6c1e3f5b7d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TABLES = ('macro_series_snapshot', 'institutional_initial', 'monthly_revenue_first_seen')
_OLD_PK = ('snapshot_date', 'meeting_date', 'outcome')
_NEW_PK = ('snapshot_date', 'snapshot_slot', 'meeting_date', 'outcome')


def _is_pg() -> bool:
    return op.get_bind().dialect.name == 'postgresql'


def upgrade() -> None:
    # 1) rate_expectations：先加欄位並用 server_default 把既有列補成 'legacy'（已無法得知當時是哪個 slot），
    #    再換 PK，最後拿掉 server_default（之後每次寫入都必須明確帶 slot）。
    op.add_column('rate_expectations', sa.Column(
        'snapshot_slot', sa.String(length=10), nullable=False, server_default='legacy'), schema='market')
    op.add_column('rate_expectations', sa.Column(
        'captured_at', sa.DateTime(timezone=True), nullable=True), schema='market')
    if _is_pg():
        # SQLite 無法 drop PK constraint：離線測試只驗欄位，PK 變更只在 Postgres（pg-scratch）驗。
        op.drop_constraint('rate_expectations_pkey', 'rate_expectations', type_='primary', schema='market')
        op.create_primary_key('rate_expectations_pkey', 'rate_expectations', list(_NEW_PK), schema='market')
        op.alter_column('rate_expectations', 'snapshot_slot', server_default=None, schema='market')

    # 2) macro_series 近 7 天的時點快照
    op.create_table(
        'macro_series_snapshot',
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('snapshot_slot', sa.String(length=10), nullable=False),
        sa.Column('series_id', sa.String(length=24), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('value', sa.Numeric(18, 6), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('as_of_cutoff', sa.DateTime(timezone=True), nullable=True),
        sa.Column('staleness_days', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('snapshot_date', 'snapshot_slot', 'series_id', 'date'),
        schema='market',
    )

    # 3) 法人初版（欄位同 institutional + captured_at）
    op.create_table(
        'institutional_initial',
        sa.Column('stock_id', sa.String(length=12), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('foreign_net', sa.BigInteger(), nullable=True),
        sa.Column('trust_net', sa.BigInteger(), nullable=True),
        sa.Column('dealer_net', sa.BigInteger(), nullable=True),
        sa.Column('total_net', sa.BigInteger(), nullable=True),
        sa.Column('market', sa.String(length=8), nullable=True),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('stock_id', 'date'),
        schema='market',
    )

    # 4) 月營收首次值（欄位同 monthly_revenue + captured_at）
    op.create_table(
        'monthly_revenue_first_seen',
        sa.Column('stock_id', sa.String(length=12), nullable=False),
        sa.Column('revenue_month', sa.Date(), nullable=False),
        sa.Column('revenue', sa.BigInteger(), nullable=True),
        sa.Column('yoy', sa.Numeric(12, 2), nullable=True),
        sa.Column('mom', sa.Numeric(12, 2), nullable=True),
        sa.Column('announce_date', sa.Date(), nullable=True),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('stock_id', 'revenue_month'),
        schema='market',
    )

    # 5) taifex_fut_oi 首次與最後抓取時間（表上線時 0 列；全部可空）
    op.add_column('taifex_fut_oi', sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=True),
                  schema='market')
    op.add_column('taifex_fut_oi', sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
                  schema='market')


def downgrade() -> None:
    # 這幾張快照表與新欄位都是「當時才抓得到」的紀錄，丟了拿不回來；有資料就拒絕降版
    # （在任何 DDL 之前），同 f2a7c4d8e913：先匯出確認備份，再自行清掉後重跑 downgrade。
    bind = op.get_bind()
    for table in _NEW_TABLES:
        rows = bind.execute(sa.text(f"SELECT count(*) FROM market.{table}")).scalar_one()
        if rows:
            raise RuntimeError(
                f"拒絕降版：{table} {rows:,} 列仍在。market schema 無備份；"
                f"請先匯出並確認備份，再 TRUNCATE market.{table} 後重跑 downgrade")
    rows = bind.execute(sa.text(
        "SELECT count(*) FROM market.taifex_fut_oi "
        "WHERE first_seen_at IS NOT NULL OR captured_at IS NOT NULL")).scalar_one()
    if rows:
        raise RuntimeError(
            f"拒絕降版：taifex_fut_oi 有 {rows:,} 列帶 first_seen_at／captured_at。market schema 無備份；"
            "請先匯出並確認備份，再清掉這兩欄的值（UPDATE … SET first_seen_at = NULL, captured_at = NULL）後重跑 downgrade")
    rows = bind.execute(sa.text(
        "SELECT count(*) FROM market.rate_expectations "
        "WHERE snapshot_slot != 'legacy' OR captured_at IS NOT NULL")).scalar_one()
    if rows:
        raise RuntimeError(
            f"拒絕降版：rate_expectations 有 {rows:,} 列帶 snapshot_slot／captured_at（Kalshi 漏抓補不回來）。"
            "market schema 無備份；請先匯出並確認備份，再 UPDATE … SET snapshot_slot = 'legacy', captured_at = NULL 後重跑 downgrade")
    # 上面的護欄通過後所有列都是 legacy，這裡實際不會觸發；留作換 PK 前的雙重保險。
    # rate_expectations 換回舊 PK 會把不同 slot 的同一合約擠成重複鍵：有重複就拒絕
    dupes = bind.execute(sa.text(
        "SELECT count(*) FROM (SELECT 1 FROM market.rate_expectations "
        "GROUP BY snapshot_date, meeting_date, outcome HAVING count(*) > 1) d")).scalar_one()
    if dupes:
        raise RuntimeError(
            f"拒絕降版：rate_expectations 有 {dupes:,} 組 (snapshot_date, meeting_date, outcome) 跨 slot 重複，"
            "無法換回舊主鍵。market schema 無備份；請先匯出並確認備份，再 DELETE 掉要捨棄的 slot 後重跑 downgrade")

    op.drop_column('taifex_fut_oi', 'captured_at', schema='market')
    op.drop_column('taifex_fut_oi', 'first_seen_at', schema='market')
    for table in reversed(_NEW_TABLES):
        op.drop_table(table, schema='market')
    if _is_pg():
        op.drop_constraint('rate_expectations_pkey', 'rate_expectations', type_='primary', schema='market')
        op.create_primary_key('rate_expectations_pkey', 'rate_expectations', list(_OLD_PK), schema='market')
    op.drop_column('rate_expectations', 'captured_at', schema='market')
    op.drop_column('rate_expectations', 'snapshot_slot', schema='market')
