"""`market.price.change` 的正負號守門。

上市走 TWSE MI_INDEX CSV，`漲跌價差` 只有絕對值，方向在獨立的 `漲跌(+/-)` 欄
（`+` / `-` / 空=平盤 / `X`=無比價）。舊版把那欄 to_numeric 成 NaN 後整欄丟掉，
符號永久遺失，下跌日在 DB 裡與上漲日無法區分——而下游 `to_daily_frame` 用
`close - change` 回推昨收，於是每個下跌日都被算成上漲。
"""

from datetime import date

import pandas as pd

from market_data import crawler, market_repo


# 真實 MI_INDEX?type=ALLBUT0999 的欄位順序與 `="..."` 包裝（crawler 會 strip 掉 `=`）。
_HEADER = (
    '"證券代號","證券名稱","成交股數","成交筆數","成交金額","開盤價","最高價",'
    '"最低價","收盤價","漲跌(+/-)","漲跌價差","最後揭示買價","最後揭示買量",'
    '"最後揭示賣價","最後揭示賣量","本益比",'
)
_ROWS = [
    # 下跌：漲跌價差 30 是絕對值，方向只在 `-` 那一欄
    '="2330","台積電","17,227,480","30,000","41,248,293,420","2,375.00","2,410.00",'
    '"2,365.00","2,350.00","-","30.00","2,349.00","100","2,350.00","100","25.00",',
    # 上漲
    '="2408","南亞科","10,000,000","20,000","5,280,000,000","520.00","542.00",'
    '"515.00","528.00","+","8.00","527.00","50","528.00","50","30.00",',
    # 平盤：方向欄為空
    '="2317","鴻海","5,000,000","10,000","1,000,000,000","200.00","201.00",'
    '"199.00","200.00"," ","0.00","199.50","10","200.00","10","15.00",',
    # 無比價（新上市首日等）：`X`，沒有可比基準
    '="9999","新掛牌","1,000","10","100,000","100.00","100.00",'
    '"100.00","100.00","X","0.00","99.00","1","100.00","1","0.00",',
]


# 第一行標題自帶資料日，crawl_price 會核對它等於請求日（審查 M3）。
_TITLE = '"115年08月21日 價格指數(臺灣證券交易所)"'


class _Resp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200


def _crawl(monkeypatch):
    monkeypatch.setattr(
        crawler, "_request",
        lambda *a, **k: _Resp("\n".join([_TITLE, _HEADER, *_ROWS])),
    )
    return crawler.crawl_price(date(2026, 8, 21))


def test_down_day_keeps_its_negative_sign(monkeypatch):
    df = _crawl(monkeypatch)
    idx = ("2330", pd.Timestamp("2026-08-21"))
    assert df.at[idx, "漲跌價差"] == -30.0
    # 反向守門：不能把所有列都翻成負的
    assert df.at[("2408", pd.Timestamp("2026-08-21")), "漲跌價差"] == 8.0


def test_flat_day_stays_zero_and_no_comparison_basis_is_null(monkeypatch):
    df = _crawl(monkeypatch)
    assert df.at[("2317", pd.Timestamp("2026-08-21")), "漲跌價差"] == 0.0
    # `X` = 無比價 ⇒ NULL，不是 0（0 是平盤，是讀數）
    assert pd.isna(df.at[("9999", pd.Timestamp("2026-08-21")), "漲跌價差"])


def test_sign_column_itself_is_not_persisted(monkeypatch):
    """方向欄只是中間產物，不該進 `market.price`（etl 也沒有它的映射）。"""
    df = _crawl(monkeypatch)
    assert crawler._SIGN_COL not in df.columns


def test_to_daily_frame_reports_down_days_as_negative():
    """即使 DB 裡的 change 仍是舊的無號值，pct_chg 也必須是負的。"""
    df = pd.DataFrame([
        {"date": "2026-08-18", "open": 2415.0, "high": 2415.0, "low": 2375.0,
         "close": 2380.0, "change": 20.0, "volume": 1, "turnover": 1},
        {"date": "2026-08-19", "open": 2340.0, "high": 2355.0, "low": 2335.0,
         "close": 2350.0, "change": 30.0, "volume": 1, "turnover": 1},
        {"date": "2026-08-20", "open": 2365.0, "high": 2375.0, "low": 2350.0,
         "close": 2375.0, "change": 25.0, "volume": 1, "turnover": 1},
    ])
    out = market_repo.to_daily_frame(df)

    # 2380 -> 2350 是 -1.26%；舊寫法 change/(close-change) 會給 +1.293%
    assert round(float(out.iloc[1]["pct_chg"]), 4) == round((2350 / 2380 - 1) * 100, 4)
    assert out.iloc[1]["pct_chg"] < 0
    # 反向守門：上漲日必須仍是正的（不能一律取負）
    assert out.iloc[2]["pct_chg"] > 0
    # 視窗第一列沒有前一日 ⇒ 缺資料，不能用可能錯號的 change 兜
    assert pd.isna(out.iloc[0]["pct_chg"])


def _two_day_frame():
    return pd.DataFrame([
        {"date": "2026-08-20", "open": 146.0, "high": 148.0, "low": 144.0,
         "close": 146.0, "change": 0.5, "volume": 4562955, "turnover": 666},
        {"date": "2026-08-21", "open": 141.5, "high": 142.0, "low": 139.0,
         "close": 140.5, "change": 0.0, "volume": 2155868, "turnover": 302},
    ])


def test_to_daily_frame_applies_ex_dividend_factor_on_event_day():
    """除權息日的價格斷崖不是真實跌幅：pct_chg 以還原後報酬為準（P1-2）。

    2458 義隆 2026-08-21：前收 146.0、收 140.5、除息因子 0.969658。
    未還原是 -3.77%；還原後 = 140.5/(146.0×0.969658)-1 ≈ -0.72%。
    """
    factors = pd.Series([0.969658], index=pd.DatetimeIndex(["2026-08-21"]))
    out = market_repo.to_daily_frame(_two_day_frame(), event_factors=factors)

    expected = (140.5 / (146.0 * 0.969658) - 1) * 100
    assert round(float(out.iloc[1]["pct_chg"]), 4) == round(expected, 4)
    assert abs(float(out.iloc[1]["pct_chg"])) < 1.0, "除息跳空不該被算成 -3.77% 的下跌"


def test_to_daily_frame_factor_only_bites_the_event_day():
    """沒有事件的日期乘 1，行為與未還原完全一致。"""
    factors = pd.Series([0.969658], index=pd.DatetimeIndex(["2026-09-01"]))
    out = market_repo.to_daily_frame(_two_day_frame(), event_factors=factors)

    assert round(float(out.iloc[1]["pct_chg"]), 4) == round((140.5 / 146.0 - 1) * 100, 4)


def test_to_daily_frame_without_factors_keeps_legacy_behavior():
    """沒給因子（舊呼叫端/測試）→ 未還原報酬，行為同 P1-2 之前。"""
    out = market_repo.to_daily_frame(_two_day_frame())
    assert round(float(out.iloc[1]["pct_chg"]), 4) == round((140.5 / 146.0 - 1) * 100, 4)
