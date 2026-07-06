"""``market`` schema ORM models (typed, English column names).

Crawlers map source (Chinese) columns to these; the dashboard reads them.
New tables/columns are added via Alembic migrations, not by editing a live DB.
"""

from datetime import date as _date

from sqlalchemy import BigInteger, Date, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from market_data.db import Base

_PRICE = Numeric(12, 4)


class Price(Base):
    """每日股價 (上市 twse + 上櫃 tpex 合併)。"""

    __tablename__ = "price"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    market: Mapped[str | None] = mapped_column(String(8))  # 'twse' | 'tpex'
    open: Mapped[float | None] = mapped_column(_PRICE)
    high: Mapped[float | None] = mapped_column(_PRICE)
    low: Mapped[float | None] = mapped_column(_PRICE)
    close: Mapped[float | None] = mapped_column(_PRICE)
    change: Mapped[float | None] = mapped_column(_PRICE)
    volume: Mapped[int | None] = mapped_column(BigInteger)  # 成交股數
    turnover: Mapped[int | None] = mapped_column(BigInteger)  # 成交金額
    transactions: Mapped[int | None] = mapped_column(Integer)  # 成交筆數
    pe_ratio: Mapped[float | None] = mapped_column(Numeric(12, 2))


class StockInfo(Base):
    """股票基本資料快照 (名稱/產業/股本)。"""

    __tablename__ = "stock_info"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    market: Mapped[str | None] = mapped_column(String(8))
    industry: Mapped[str | None] = mapped_column(String(16))
    listed_date: Mapped[_date | None] = mapped_column(Date)
    par_value: Mapped[float | None] = mapped_column(Numeric(12, 4))
    paid_in_capital: Mapped[int | None] = mapped_column(BigInteger)
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger)


class Valuation(Base):
    """估值三率 (每日,每股)。"""

    __tablename__ = "valuation"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    pe_ratio: Mapped[float | None] = mapped_column(Numeric(12, 2))
    pb_ratio: Mapped[float | None] = mapped_column(Numeric(12, 2))
    dividend_yield: Mapped[float | None] = mapped_column(Numeric(8, 4))


class MarketIndex(Base):
    """大盤 / 類股指數 (每日),如 TAIEX、櫃買指數。"""

    __tablename__ = "market_index"

    index_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    close: Mapped[float | None] = mapped_column(Numeric(14, 2))
    change: Mapped[float | None] = mapped_column(Numeric(14, 2))
    turnover: Mapped[int | None] = mapped_column(BigInteger)  # 市場成交金額


class Institutional(Base):
    """三大法人買賣超 (每日,每股),單位:股。"""

    __tablename__ = "institutional"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    foreign_net: Mapped[int | None] = mapped_column(BigInteger)  # 外資買賣超
    trust_net: Mapped[int | None] = mapped_column(BigInteger)  # 投信
    dealer_net: Mapped[int | None] = mapped_column(BigInteger)  # 自營商
    total_net: Mapped[int | None] = mapped_column(BigInteger)  # 三大法人合計


class Margin(Base):
    """融資融券 (每日,每股),單位:交易單位/張。"""

    __tablename__ = "margin"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    margin_balance: Mapped[int | None] = mapped_column(BigInteger)  # 融資今日餘額
    margin_buy: Mapped[int | None] = mapped_column(BigInteger)
    margin_sell: Mapped[int | None] = mapped_column(BigInteger)
    short_balance: Mapped[int | None] = mapped_column(BigInteger)  # 融券今日餘額
    short_buy: Mapped[int | None] = mapped_column(BigInteger)
    short_sell: Mapped[int | None] = mapped_column(BigInteger)


class ExDividend(Base):
    """除權息計算結果 (每股,以除權息日為 date)。"""

    __tablename__ = "ex_dividend"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    close_before: Mapped[float | None] = mapped_column(Numeric(12, 4))  # 除權息前收盤價
    reference_price: Mapped[float | None] = mapped_column(Numeric(12, 4))  # 參考價
    value: Mapped[float | None] = mapped_column(Numeric(12, 6))  # 權值+息值
    rights_type: Mapped[str | None] = mapped_column(String(8))  # 權/息/權息


class MonthlyRevenue(Base):
    """月營收 (每股,以營收所屬月份為 key)。"""

    __tablename__ = "monthly_revenue"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    revenue_month: Mapped[_date] = mapped_column(Date, primary_key=True)  # 該月 1 號
    revenue: Mapped[int | None] = mapped_column(BigInteger)  # 當月營收(千元,MOPS 原始單位)
    yoy: Mapped[float | None] = mapped_column(Numeric(12, 2))  # 去年同月增減%
    mom: Mapped[float | None] = mapped_column(Numeric(12, 2))  # 上月比較增減%
    announce_date: Mapped[_date | None] = mapped_column(Date)  # 公告日(point-in-time)


class FinancialStatement(Base):
    """財報 (長格式):避開 900 欄寬表,任意會計科目不需改 schema。"""

    __tablename__ = "financial_statement"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)  # 財報發布/對齊日
    statement_type: Mapped[str] = mapped_column(String(24), primary_key=True)
    account: Mapped[str] = mapped_column(String(128), primary_key=True)  # 會計項目
    value: Mapped[float | None] = mapped_column(Numeric(28, 4))
