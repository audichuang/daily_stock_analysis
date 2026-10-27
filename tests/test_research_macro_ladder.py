"""scripts/research_macro_ladder.py 的純函式：07:30 資訊集對齊、夜盤契約選擇、訓練窗不前視、事件計數。"""

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import research_macro_ladder  # noqa: E402
from research_macro_ladder import (  # noqa: E402
    AVAILABLE_RULE,
    FX_MAX_DEV,
    YF_SERIES,
    adr_premium,
    align_available,
    build_features,
    build_targets,
    drop_bad_ticks,
    incremental_r2,
    new_events,
    night_returns,
    onsets,
    rolling_oos,
    train_bounds,
)

# 2026-10-19 是週一；台股交易日週一～週五
TW = pd.DatetimeIndex(pd.bdate_range("2026-10-19", "2026-10-23"))


def _us(values_by_day):
    idx = pd.DatetimeIndex(pd.to_datetime(list(values_by_day)))
    return pd.Series(list(values_by_day.values()), index=idx, dtype=float)


def test_us_close_on_same_date_is_not_visible_at_0730():
    # 美股每天收盤值互不相同，才分辨得出 D、D−1、D−2
    us = _us({"2026-10-15": 1, "2026-10-16": 2, "2026-10-19": 3, "2026-10-20": 4,
              "2026-10-21": 5, "2026-10-22": 6, "2026-10-23": 7})
    got = align_available(TW, us, "us_close")
    # 週一 07:30 只看得到上週五（10-16）收盤；週二看得到週一；同日（台北隔天清晨才收）的值不可用
    assert got.tolist() == [2, 3, 4, 5, 6]


def test_us_alignment_is_not_over_lagged():
    # 反向：多推一天（用 D−2）會丟掉 07:30 已可得的美股收盤
    us = _us({"2026-10-16": 2, "2026-10-19": 3, "2026-10-20": 4})
    got = align_available(pd.DatetimeIndex(["2026-10-20", "2026-10-21"]), us, "us_close")
    assert got.tolist() == [3, 4]


def test_us_holiday_does_not_shift_by_row():
    # 美股週一休市：台股週二只看得到上週五，不能因為 shift(1) 拿到別的東西
    us = _us({"2026-10-16": 2, "2026-10-20": 4})
    got = align_available(TW, us, "us_close")
    # 週一、週二都只看得到上週五；週二的美股收盤到台股週三才可用
    assert got.tolist() == [2, 2, 4, 4, 4]


def test_fred_daily_waits_one_us_business_day():
    # DGS10 的 10-19（週一）值，保守視為 10-20 才上 FRED → 台股 10-21 才可用
    fred = _us({"2026-10-16": 4.0, "2026-10-19": 4.1})
    got = align_available(TW, fred, "next_us_bday")
    assert got.iloc[0] != got.iloc[0]  # 週一：10-16 的值週一（10-19）才 available，嚴格小於不成立
    assert got.tolist()[1:] == [4.0, 4.1, 4.1, 4.1]


def test_fred_daily_skips_us_federal_holiday():
    # 2024-11-28 感恩節 H.15 不發布：11-27（週三）的值美東 11-29 才上 FRED（台北 11-30 清晨），
    # 台股 11-29（週五）07:30 還不可用、12-02（週一）才可用。只跳週末的 BDay 會在 11-29 前視拿到 4.25；
    # 反向：延後兩個營業日會讓 12-02 也拿不到
    fred = _us({"2024-11-26": 4.30, "2024-11-27": 4.25})
    tw = pd.DatetimeIndex(["2024-11-28", "2024-11-29", "2024-12-02"])
    got = align_available(tw, fred, "next_us_bday")
    assert got.tolist() == [4.30, 4.30, 4.25]


def test_icsa_saturday_week_released_thursday_usable_friday():
    icsa = _us({"2026-10-10": 200_000, "2026-10-17": 250_000})
    got = align_available(TW, icsa, "icsa_thursday")
    # 10-17（週六）那週在 10-22（週四）美東早上公布 ＝ 台北週四晚上 → 週四 07:30 還看不到、週五才看得到
    assert got.tolist() == [200_000, 200_000, 200_000, 200_000, 250_000]


def test_new_events_counts_each_trigger_once_on_first_visible_day():
    flags = pd.Series([False, True, True, False],
                      index=pd.to_datetime(["2026-10-15", "2026-10-16", "2026-10-17", "2026-10-19"]))
    ev = new_events(TW, flags, "us_close", "2026-10-16")
    # 10-16、10-17 的觸發在上一個台股日（10-16）之後才可得，都在台股 10-19（週一）第一次可見，只算一次；
    # 10-19 的美股日不觸發
    assert ev.tolist() == [True, False, False, False, False]


def test_new_events_ignores_warmup_triggers_on_first_research_day():
    # 暖機期（研究起點前半年）有觸發、之後全部沒有：第一個台股日不能把暖機累計當成新事件
    flags = pd.Series([True] + [False] * 5,
                      index=pd.to_datetime(["2009-07-01", "2009-12-28", "2009-12-29",
                                            "2009-12-30", "2009-12-31", "2010-01-04"]))
    ev = new_events(pd.bdate_range("2010-01-04", "2010-01-08"), flags, "us_close", "2009-12-31")
    assert ev.tolist() == [False] * 5


def test_new_events_first_day_counts_trigger_from_real_previous_tw_day():
    # 2010-01-01 台股休市，真正的上一個台股日是 2009-12-31。12-31 的美股收盤觸發在台北 01-01 清晨才收，
    # 01-04 第一次可見，必須算新事件（用「前一個營業日」01-01 當參考會把它當成已見過）
    flags = pd.Series([True, False, False, False, True, False],
                      index=pd.to_datetime(["2009-07-01", "2009-12-28", "2009-12-29",
                                            "2009-12-30", "2009-12-31", "2010-01-04"]))
    ev = new_events(pd.bdate_range("2010-01-04", "2010-01-08"), flags, "us_close", "2009-12-31")
    assert ev.tolist() == [True, False, False, False, False]


def test_new_events_first_day_ignores_trigger_visible_on_previous_tw_day():
    # 反向：12-30 的觸發在 12-31 07:30 已可得、不是 01-04 的新事件；參考日退到 12-30 會誤算成新事件
    flags = pd.Series([True, False, False, True, False, False],
                      index=pd.to_datetime(["2009-07-01", "2009-12-28", "2009-12-29",
                                            "2009-12-30", "2009-12-31", "2010-01-04"]))
    ev = new_events(pd.bdate_range("2010-01-04", "2010-01-08"), flags, "us_close", "2009-12-31")
    assert ev.tolist() == [False] * 5


def test_new_events_counts_trigger_after_series_starts_late():
    # 反向：外部序列晚於研究起點才開始（前幾天整列不可得），第一筆可得的觸發仍要算
    flags = pd.Series([True, False], index=pd.to_datetime(["2026-10-19", "2026-10-20"]))
    ev = new_events(TW, flags, "us_close", "2026-10-16")
    assert ev.tolist() == [False, True, False, False, False]


def _tx(date, contract, session, volume, close=None, settle=None):
    return {"date": date, "contract": contract, "session": session, "open": close,
            "close": close, "settle": settle, "volume": volume}


def test_night_contract_is_chosen_from_previous_day_volume():
    d0, d1 = dt.date(2026, 10, 19), dt.date(2026, 10, 20)
    rows = [
        _tx(d0, "202610", "一般", 1000, close=100, settle=100),
        _tx(d0, "202611", "一般", 10, close=200, settle=200),
        _tx(d1, "202610", "盤後", 50, close=101),
        _tx(d1, "202611", "盤後", 5000, close=220),
        # d1 日盤（09:00 之後）換月：成交量轉到 202611，但這在 07:30 不可得
        _tx(d1, "202610", "一般", 10, close=101, settle=101),
        _tx(d1, "202611", "一般", 9000, close=221, settle=221),
    ]
    got = night_returns(rows, pd.DatetimeIndex([d0, d1]))
    assert np.isnan(got.iloc[0])
    assert got.iloc[1] == 101 / 100 - 1


def test_night_skips_contract_that_expired_without_night_session():
    # 結算日 d0：量最大的是當天到期的 202610，它沒有 d1 的夜盤；要改用有夜盤的 202611，不能整天 NaN
    d0, d1 = dt.date(2026, 10, 21), dt.date(2026, 10, 22)
    rows = [
        _tx(d0, "202610", "一般", 9000, close=100, settle=100),
        _tx(d0, "202611", "一般", 5000, close=200, settle=200),
        _tx(d1, "202611", "盤後", 3000, close=210),
    ]
    got = night_returns(rows, pd.DatetimeIndex([d0, d1]))
    assert got.iloc[1] == 210 / 200 - 1


def test_train_bounds_excludes_unresolved_targets():
    # R3（h=3）的第 s 列要到 s+2 收盤才知道：預測第 10 列只能用 s ≤ 7
    assert train_bounds(10, 3, 756) == (0, 8)
    assert train_bounds(10, 1, 756) == (0, 10)
    assert train_bounds(900, 1, 756) == (144, 900)


def test_rolling_oos_uses_only_resolved_rows():
    # 常數特徵 → 預測就是訓練窗 y 的平均；y＝列號，平均值直接揭露用到哪幾列
    n = 12
    X = np.ones((n, 1))
    y = np.arange(n, dtype=float)
    for h in (1, 3):
        pred, bench = rolling_oos(X, y, horizon=h, window=4, min_train=1)
        i = 9
        end = i - h + 1
        assert pred[i] == y[max(0, end - 4):end].mean()
        assert bench[i] == pred[i]


def test_targets_and_lagged_features_have_no_same_day_close():
    tw = pd.DataFrame({"open": [100, 101, 103, 102, 105, 104, 106],
                       "close": [101, 102, 102, 104, 104, 107, 105]},
                      index=pd.bdate_range("2026-10-12", periods=7), dtype=float)
    t = build_targets(tw)
    assert t["CO"].iloc[1] == 101 / 101 - 1
    assert t["OC"].iloc[2] == 102 / 103 - 1
    assert t["R3"].iloc[2] == 104 / 103 - 1     # open_t → close_{t+2}
    cols = ["SOX", "NDX", "SPX", "TSM", "DXY", "TWD", "BRENT", "HYG", "VIX", "DGS10", "DGS2", "ICSA_CHG"]
    # 每欄逐日不同的值，才分辨得出對齊後是否又被往前／往後挪
    aligned = pd.DataFrame({c: [10.0 + k + j * 0.5 * (j + 1) for j in range(7)] for k, c in enumerate(cols)},
                           index=tw.index)
    f = build_features(tw, aligned, pd.Series(0.0, index=tw.index), pd.Series(0.0, index=tw.index))
    # 07:30 時台股最新收盤是 t−1
    assert f["tw_cc1"].iloc[3] == 102 / 102 - 1
    assert f["tw_oc1"].iloc[3] == 102 / 103 - 1
    # 外部特徵＝「t 可得水準 ÷ t−1 台股日可得水準 − 1」，不能挪到 t+1（前視）或 t−2（過度落後）
    for col, name in (("sox", "SOX"), ("twd", "TWD"), ("brent", "BRENT")):
        lv = aligned[name]
        assert f[col].iloc[3] == lv.iloc[3] / lv.iloc[2] - 1
    assert f["dgs10"].iloc[3] == aligned["DGS10"].iloc[3] - aligned["DGS10"].iloc[2]
    assert f["icsa"].iloc[3] == aligned["ICSA_CHG"].iloc[3]


def test_available_rule_matches_0730_release_times():
    # TWD=X 日線收盤時點錯置要晚一天；FRED 日資料隔一個美國營業日才上；ICSA 週四晚上公布
    assert AVAILABLE_RULE["TWD"] == "next_day"
    assert AVAILABLE_RULE["DGS10"] == "next_us_bday"
    assert AVAILABLE_RULE["DGS2"] == "next_us_bday"
    assert AVAILABLE_RULE["ICSA"] == "icsa_thursday"
    # 反向：其餘 yfinance 序列不能被過度延後
    assert {k: v for k, v in AVAILABLE_RULE.items() if k in YF_SERIES and k != "TWD"} == {
        k: "us_close" for k in YF_SERIES if k != "TWD"}


def test_adr_premium_uses_previous_tw_close():
    days = pd.bdate_range("2026-10-19", periods=3)
    tsm = pd.Series([200.0, 210.0, 220.0], index=days)
    twd = pd.Series([30.0, 31.0, 32.0], index=days)
    raw_2330 = pd.Series([1000.0, 1100.0, 1200.0], index=days)
    prem = adr_premium(tsm, twd, raw_2330)
    # 07:30 時 2330 最新收盤是前一台股日；同日收盤要 13:30 才有
    assert np.isnan(prem.iloc[0])
    assert prem.iloc[1] == 210 * 31 / (5 * 1000) - 1
    assert prem.iloc[2] == 220 * 32 / (5 * 1100) - 1


def test_main_blanks_storage_database_url_even_when_exported(monkeypatch, tmp_path):
    # shell 已 export 正式應用庫 URL 時也要清成空字串（setdefault 不會覆寫）
    monkeypatch.setenv("STORAGE_DATABASE_URL", "postgresql://prod/dsa")
    assert research_macro_ladder.main(["--cache-only", "--cache-dir", str(tmp_path)]) == 0
    assert research_macro_ladder.os.environ["STORAGE_DATABASE_URL"] == ""


def test_drop_bad_ticks_uses_past_only():
    s = pd.Series([31.0, 31.1, 31.2, 1.8, 31.3, 31.2],
                  index=pd.bdate_range("2011-10-20", periods=6))
    clean, dropped = drop_bad_ticks(s, FX_MAX_DEV)
    assert dropped == [dt.date(2011, 10, 25)]
    assert len(clean) == 5
    # 反向：2025-05 台幣兩天升值約 8% 是真實行情，不能被當壞價丟掉
    real = pd.Series([32.5, 32.4, 32.3, 31.0, 29.9, 30.1], index=pd.bdate_range("2025-04-28", periods=6))
    assert drop_bad_ticks(real, FX_MAX_DEV)[1] == []


def test_onsets_and_incremental_r2():
    st = onsets([True, True, False, True, False, False, True], gap=3)
    assert np.isnan(st[1])
    assert st.tolist()[0] == 1 and st.tolist()[3] == 1 and st.tolist()[6] == 1
    rng = np.random.default_rng(0)
    y = rng.normal(size=200)
    r = incremental_r2(y, np.zeros(200), y * 0.5, np.zeros(200), block=10, n_boot=200)
    assert r["dr2"] > 0 and r["ci"][0] > 0
