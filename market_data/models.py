"""``market`` schema ORM models (typed, English column names).

Crawlers map source (Chinese) columns to these; the dashboard reads them.
New tables/columns are added via Alembic migrations, not by editing a live DB.
"""

from datetime import date as _date
from datetime import datetime as _datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, Numeric, String
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


class InstitutionalInitial(Base):
    """三大法人「初版」快照（append-only）：``daily_update`` 首次抓到的 T86／TPEx 值。

    ``institutional`` 隔日會被 ``crawl.REVISED_SOURCES`` 的 refresh 整日換血成定版，初版就消失；
    這張表只在 daily 路徑以 ``ON CONFLICT DO NOTHING`` 寫入，``backfill``／``refresh`` 都不寫，
    所以歷史回補不會冒充初版。欄位與 ``institutional`` 相同，另加 ``captured_at``（抓到的時刻）。
    「初版」＝daily 補缺路徑**第一次抓到**的值，不保證是 18:00 當晚抓的：前一晚失敗或 T86 還沒出，
    隔天（07:30 ``make morning`` 也跑 daily）補抓到的可能已是定版。研究要讀初版時，篩 ``captured_at``
    落在該交易日當晚的列；上線前的日期沒有初版。
    """

    __tablename__ = "institutional_initial"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    foreign_net: Mapped[int | None] = mapped_column(BigInteger)
    trust_net: Mapped[int | None] = mapped_column(BigInteger)
    dealer_net: Mapped[int | None] = mapped_column(BigInteger)
    total_net: Mapped[int | None] = mapped_column(BigInteger)
    market: Mapped[str | None] = mapped_column(String(8))
    captured_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))


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


class MonthlyRevenueFirstSeen(Base):
    """月營收「首次看到的值」快照（append-only）：更正後 ``monthly_revenue`` 不留原值。

    只由 ``daily_update`` 的 ``crawl_monthly_revenue(record_first_seen=True)`` 以
    ``ON CONFLICT DO NOTHING`` 寫入；手動 ``cli`` 與 ``backfill_pit_revenue`` 都不寫。
    欄位同 ``monthly_revenue`` 加 ``captured_at``。上線第一天抓到的「上月」值可能已修正過，
    那天 ``captured_at`` 的列不能當首次值。
    """

    __tablename__ = "monthly_revenue_first_seen"

    stock_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    revenue_month: Mapped[_date] = mapped_column(Date, primary_key=True)
    revenue: Mapped[int | None] = mapped_column(BigInteger)
    yoy: Mapped[float | None] = mapped_column(Numeric(12, 2))
    mom: Mapped[float | None] = mapped_column(Numeric(12, 2))
    announce_date: Mapped[_date | None] = mapped_column(Date)
    captured_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))


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
    # 首次入庫時刻（設過不覆蓋）與最後一次抓取時刻（每次重抓更新）；期交所事後更正會覆蓋數值，
    # 靠這兩欄才分得出「第一次看到」與「最後一次確認」
    first_seen_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))


class MacroSeries(Base):
    """總經／國際盤日線（美債殖利率、美元、匯率、原油、黃金、費半、韓股等），一序列一日一列。

    ``series_id`` 是 yfinance 代號（``^TNX``、``CL=F``）或 ``FRED:DGS2`` 這類加來源前綴的代號；
    清單只有一份，在 ``market_data/macro.py`` 的 ``SERIES``。``date`` 是資料列自帶的交易日、
    不是抓取日；期貨／匯率最後一列可能是盤中值，下次抓取同日會被覆蓋。``value`` 是收盤值，
    殖利率類單位是百分比（4.99 = 4.99%）。寫入見 ``market_data/macro.py``。
    """

    __tablename__ = "macro_series"

    series_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    value: Mapped[float | None] = mapped_column(Numeric(18, 6))
    source: Mapped[str | None] = mapped_column(String(16))  # yfinance | fred
    updated_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))


class MacroSeriesSnapshot(Base):
    """``macro_series`` 的時點快照（append-only 精神）：每次抓取各 slot 留一份最近的列。

    ``macro_series`` 每天整段重抓覆蓋，看不出「當時手上有什麼」。這張表只存
    ``date >= snapshot_date - 7`` 的列（約 22 序列 × 5 列；全存會每天約 1.1 萬列），
    ``snapshot_slot`` 同 ``rate_expectations``（台北時間 premarket／intraday／postclose）。
    ``received_at`` 是抓到的時刻、``as_of_cutoff`` 是這次抓取開始的時刻、``staleness_days`` 是
    ``snapshot_date - date``。同 slot 重跑以 upsert 覆蓋、不同 slot 各自保留。
    """

    __tablename__ = "macro_series_snapshot"

    snapshot_date: Mapped[_date] = mapped_column(Date, primary_key=True)
    snapshot_slot: Mapped[str] = mapped_column(String(10), primary_key=True)
    series_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    date: Mapped[_date] = mapped_column(Date, primary_key=True)
    value: Mapped[float | None] = mapped_column(Numeric(18, 6))
    source: Mapped[str | None] = mapped_column(String(16))
    received_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))
    as_of_cutoff: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))
    staleness_days: Mapped[int | None] = mapped_column(Integer)


class RateExpectation(Base):
    """Fed 每場會議各結果的市場隱含機率快照（Kalshi ``KXFEDDECISION``），每天一份。

    ``outcome``：``hike_gt25``、``hike_25``、``hold``、``cut_25``、``cut_gt25``。``prob_mid`` 是
    買賣價中點（``last_price`` 可能是很久以前的成交，不能當機率）；各結果是獨立合約，
    中點加總不一定剛好 1。``snapshot_date`` 是抓取當天（台北日期），``source_updated_at`` 是
    Kalshi 回應裡該合約的最後更新時間——舊了代表沒人交易。
    """

    __tablename__ = "rate_expectations"

    snapshot_date: Mapped[_date] = mapped_column(Date, primary_key=True)
    snapshot_slot: Mapped[str] = mapped_column(String(10), primary_key=True)  # premarket|intraday|postclose|legacy
    meeting_date: Mapped[_date] = mapped_column(Date, primary_key=True)
    outcome: Mapped[str] = mapped_column(String(12), primary_key=True)
    prob_mid: Mapped[float | None] = mapped_column(Numeric(6, 4))
    yes_bid: Mapped[float | None] = mapped_column(Numeric(6, 4))
    yes_ask: Mapped[float | None] = mapped_column(Numeric(6, 4))
    last_price: Mapped[float | None] = mapped_column(Numeric(6, 4))
    volume: Mapped[float | None] = mapped_column(Numeric(18, 2))
    open_interest: Mapped[float | None] = mapped_column(Numeric(18, 2))
    source_updated_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(16))  # kalshi
    captured_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))


class EventCalendar(Base):
    """重大事件行事曆：FOMC 決議日、美股巨頭財報日、美國經濟數據、ISM、央行理監事會。

    鍵是 ``(event_type, symbol, label)``，``event_date`` 是可變欄位——財報日常改期，鍵含日期的話
    改期會多出一列而不是更新。``label`` 對 FOMC 是會議月份（``2026-10``），對財報是財報日所在
    季度（``2026Q4``）。``status``：``confirmed``（官方來源或兩來源一致）／``estimated``
    （單一非官方來源，例如 yfinance 財報日）。寫入見 ``market_data/macro.py``。

    經濟數據（``cpi``／``nfp``／``unrate``／``retail``／``pce``／``claims``，``symbol='US'``，``label`` 是
    公布日 ISO）另有 ``released_at``（公布時刻，aware）與 ``series_id``（對應 FRED 序列）；公布後
    ``actual_value``／``prior_value``／``observation_date`` 存 ALFRED **首發 vintage**（``actual_vintage``）
    的值，不是 ``macro_series`` 裡會被修訂的值。``ism`` 是規則推估（``estimated``）、``cbc`` 是央行常數表。
    **不寫「高於／低於預期」：沒有 PIT 共識，只存首發實際值與前值。** 這幾欄都可空，舊列（FOMC、財報）為 NULL。
    """

    __tablename__ = "event_calendar"

    event_type: Mapped[str] = mapped_column(String(16), primary_key=True)  # fomc|earnings|cpi|nfp|unrate|retail|pce|claims|ism|cbc
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    label: Mapped[str] = mapped_column(String(16), primary_key=True)
    event_date: Mapped[_date] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(12))
    title: Mapped[str | None] = mapped_column(String(128))
    time_note: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str | None] = mapped_column(String(24))
    updated_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True))
    series_id: Mapped[str | None] = mapped_column(String(24))  # FRED:PAYEMS
    observation_date: Mapped[_date | None] = mapped_column(Date)
    actual_value: Mapped[float | None] = mapped_column(Numeric(18, 6))
    prior_value: Mapped[float | None] = mapped_column(Numeric(18, 6))
    actual_vintage: Mapped[_date | None] = mapped_column(Date)
    actual_source: Mapped[str | None] = mapped_column(String(16))  # alfred
