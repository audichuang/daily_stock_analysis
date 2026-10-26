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
    """估值三率 (每日,每股)。上市 BWIBBU、上櫃 peQryDate。"""

    __tablename__ = "valuation"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    pe_ratio: Mapped[float | None] = mapped_column(Numeric(12, 2))
    pb_ratio: Mapped[float | None] = mapped_column(Numeric(12, 2))
    dividend_yield: Mapped[float | None] = mapped_column(Numeric(8, 4))
    # NULL = 上市（TWSE，歷史列沿用）、'tpex' = 上櫃。resume／replace／health 依此分市場，
    # 兩邊各自補缺、互不刪除（見 crawl.SOURCE_MARKET）。
    market: Mapped[str | None] = mapped_column(String(8))


class MarketIndex(Base):
    """大盤 / 類股指數 (每日),如 TAIEX、櫃買指數。"""

    __tablename__ = "market_index"

    index_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Numeric(14, 2))
    high: Mapped[float | None] = mapped_column(Numeric(14, 2))
    low: Mapped[float | None] = mapped_column(Numeric(14, 2))
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
    # NULL = 上市（TWSE，歷史列沿用）、'tpex' = 上櫃。resume／replace／health 依此分市場，
    # 兩邊各自補缺、互不刪除（見 crawl.SOURCE_MARKET）。
    market: Mapped[str | None] = mapped_column(String(8))


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
    # NULL = 上市（TWSE，歷史列沿用）、'tpex' = 上櫃。resume／replace／health 依此分市場，
    # 兩邊各自補缺、互不刪除（見 crawl.SOURCE_MARKET）。
    market: Mapped[str | None] = mapped_column(String(8))


class ExDividend(Base):
    """除權息計算結果 (每股,以除權息日為 date)。"""

    __tablename__ = "ex_dividend"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    close_before: Mapped[float | None] = mapped_column(Numeric(12, 4))  # 除權息前收盤價
    reference_price: Mapped[float | None] = mapped_column(Numeric(12, 4))  # 參考價
    value: Mapped[float | None] = mapped_column(Numeric(12, 6))  # 權值+息值
    rights_type: Mapped[str | None] = mapped_column(String(8))  # 權/息/權息


class PriceAdjustment(Base):
    """前復權因子 (每股每事件日)——``price`` 是未還原價,算報酬/均線前要套這張表。

    為什麼不直接用 ``ex_dividend``:那張表只有 TWSE 上市的息/權/權息,缺三類事件——
    上櫃(TPEx)全部、股票分割(面額變更)、減資。缺了會讓除息/分割跳空被當成真實下跌
    (0050 的 1:4 分割曾讓回測基準顯示 2025 年 -65.79%)。

    ``factor`` = reference_price / close_before(<1 為除息/分割,>1 為減資)。
    前復權時把 ``date`` **之前**的價格乘上 factor,最新價維持原值。

    ``source`` 標明可信度:``twse_twt49u``/``twse_twtauu`` 為官方公告值;``inferred_price``
    是由價格跳空回推——台股有 ±10% 漲跌幅限制(ETF 除外),故非 ETF 的單日 >15% 跳空
    必為公司行動,但回推值含當日自身漲跌(誤差 ≤10%),優先權低於官方值。
    """

    __tablename__ = "price_adjustment"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)  # 事件生效日(除權息日/恢復買賣日)
    factor: Mapped[float] = mapped_column(Numeric(18, 10), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # dividend|split|reduction|inferred
    source: Mapped[str] = mapped_column(String(24), nullable=False)  # twse_twt49u|twse_twtauu|tpex_revivt|inferred_price
    close_before: Mapped[float | None] = mapped_column(Numeric(12, 4))
    reference_price: Mapped[float | None] = mapped_column(Numeric(12, 4))


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


class FundInfo(Base):
    """境內基金（含 ETF、各級別）基本資料。

    ``fund_id`` 用投信投顧公會的「基金統編」（級別另帶字母尾碼，如 ``00526748A``）：
    公會每日淨值檔與基本資料檔都以它為鍵、各自唯一；鉅亨回應裡的 ``sitca`` 欄也是它。
    公會的「基金代號」（如 ``DDO04``）在淨值檔內重複 529 次，不能當鍵。
    ``cnyes_id`` 是非官方來源的對照（以 ISIN 驗證後才寫入），只給補歷史淨值與持股用。
    """

    __tablename__ = "fund_info"

    fund_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    company: Mapped[str | None] = mapped_column(String(32))  # 投信名稱
    isin: Mapped[str | None] = mapped_column(String(16))
    sitca_code: Mapped[str | None] = mapped_column(String(16))  # 公會基金代號（非唯一）
    type_code: Mapped[str | None] = mapped_column(String(8))  # AA1 國內股票型…
    type_name: Mapped[str | None] = mapped_column(String(64))
    invest_area: Mapped[str | None] = mapped_column(String(128))
    currency: Mapped[str | None] = mapped_column(String(8))  # 計價幣別
    inception_date: Mapped[_date | None] = mapped_column(Date)
    aum: Mapped[int | None] = mapped_column(BigInteger)  # 級別規模（規模幣別）
    aum_currency: Mapped[str | None] = mapped_column(String(8))
    aum_date: Mapped[_date | None] = mapped_column(Date)
    dividend_policy: Mapped[str | None] = mapped_column(String(128))
    cnyes_id: Mapped[str | None] = mapped_column(String(16))


class FundNav(Base):
    """境內基金每日淨值。``date`` 是淨值日（來源每列自帶），不是抓取日。

    ``source``：``sitca``（公會每日檔，官方）或 ``cnyes``（鉅亨歷史，非官方，只補缺日、
    不覆蓋官方值）。
    """

    __tablename__ = "fund_nav"

    fund_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    nav: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    change: Mapped[float | None] = mapped_column(Numeric(18, 6))
    change_pct: Mapped[float | None] = mapped_column(Numeric(12, 6))
    source: Mapped[str] = mapped_column(String(8), nullable=False)


class HoldingDist(Base):
    """集保股權分散表（每週，每股每持股分級一列），來源 TDCC。

    ``level`` 沿用集保開放資料（1-5）的編號：1~15 為持股分級（15 = 1,000,001 股以上，
    即千張大戶），16 = 差異數調整、17 = 合計。``date`` 是集保資料日（週五，遇假日提前）。
    開放資料只給最新一週；歷史靠 TDCC 個股查詢頁（約 51 週）逐檔回補，那頁沒有 16。
    """

    __tablename__ = "holding_dist"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    level: Mapped[int] = mapped_column(Integer, primary_key=True)
    holders: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    pct: Mapped[float | None] = mapped_column(Numeric(8, 2))  # 占集保庫存數比例 %


class TaifexFutOI(Base):
    """期交所三大法人期貨未平倉（每日，每商品每身份別一列），來源 ``futContractsDateDown``。

    目前只入庫臺股期貨（大台 ``TXF``，不含小台）。``identity``：``dealer`` 自營商、``trust`` 投信、
    ``foreign`` 外資及陸資。口數單位：口；契約金額單位：千元。淨額＝多方−空方，負值＝淨空。
    ``date`` 是回應每列自帶的交易日，不是抓取日；只從開始入庫那天起每日累積，不回補更早歷史
    （寫入見 ``market_data/taifex.py``）。
    """

    __tablename__ = "taifex_fut_oi"

    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    commodity_id: Mapped[str] = mapped_column(String(8), primary_key=True)  # TXF
    identity: Mapped[str] = mapped_column(String(8), primary_key=True)  # dealer|trust|foreign
    long_oi: Mapped[int | None] = mapped_column(BigInteger)
    short_oi: Mapped[int | None] = mapped_column(BigInteger)
    net_oi: Mapped[int | None] = mapped_column(BigInteger)
    long_oi_amount: Mapped[int | None] = mapped_column(BigInteger)
    short_oi_amount: Mapped[int | None] = mapped_column(BigInteger)
    net_oi_amount: Mapped[int | None] = mapped_column(BigInteger)
