# -*- coding: utf-8 -*-
"""Tests for scripts.screen_tw 的純計算層（不碰 DB / 網路）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from screen_tw import compute_factors, tag  # noqa: E402


def _bars(closes, volume=1000, turnover=3e8):
    """把收盤價序列包成 compute_factors 需要的日 K DataFrame（high/low 各 ±1%）。"""
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=len(closes), freq="D"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [volume] * len(closes),
        "turnover": [turnover] * len(closes),
    })


def test_moving_averages_and_returns():
    # 100, 101, ... 169：等差序列讓均線與報酬可手算
    f = compute_factors(_bars([100.0 + i for i in range(70)]))
    assert f["close"] == 169.0
    assert f["ma5"] == pytest.approx((165 + 166 + 167 + 168 + 169) / 5)
    assert f["ma20"] == pytest.approx(sum(range(150, 170)) / 20)
    assert f["d1"] == pytest.approx(169 / 168 - 1)
    assert f["d20"] == pytest.approx(169 / 149 - 1)
    assert f["bias20"] > 0  # 單調上漲必然正乖離


def test_position_and_drawdown_on_pullback():
    """先漲後跌：pos20 應落在低檔、from_hi60 應為負。"""
    closes = [100.0 + i for i in range(60)] + [159.0 - 2 * i for i in range(10)]
    f = compute_factors(_bars(closes))
    assert f["pos20"] < 0.2
    assert f["from_hi60"] < 0
    assert f["rsi14"] < 50


def test_vol_ratio_flags_volume_spike():
    df = _bars([100.0] * 70)
    df.loc[df.index[-1], "volume"] = 5000  # 末日爆量 5 倍
    assert compute_factors(df)["vol_ratio"] > 3


def _row(**kw):
    base = {
        "d1": 0.0, "d5": 0.0, "d20": 0.0, "bias20": 0.0, "rsi14": 50.0,
        "turnover20": 5e8, "dividend_yield": 1.0, "pb_ratio": 3.0, "pe_ratio": 20.0,
        "yoy": 0.0, "industry": "17", "margin_chg5": 0.0, "vol_ratio": 1.0,
    }
    return pd.Series({**base, **kw})


def test_tag_marks_daily_crash():
    """回歸守門：當日爆跌必須被標記，否則只看 20 日動能會把高位長黑股排到前面。"""
    assert "⚠⚠當日重挫爆量" in tag(_row(d1=-0.07, vol_ratio=2.0), market_d1=-0.01)
    assert "⚠⚠當日重挫" in tag(_row(d1=-0.07), market_d1=-0.01)
    assert not any("當日重挫" in t for t in tag(_row(d1=-0.02), market_d1=-0.01))


def test_tag_marks_semiconductor_linkage_and_thin_volume():
    t = tag(_row(industry="24", turnover20=5e7), market_d1=0.0)
    assert "⚠費半連動" in t
    assert "⚠量能薄" in t
    assert "⚠費半連動" not in tag(_row(industry="17"), market_d1=0.0)


def test_tag_counter_trend_is_relative_to_market():
    """個股 -1% 在大盤 -3% 的日子算抗跌，在大盤持平的日子不算。"""
    assert "逆勢抗跌" in tag(_row(d1=-0.01), market_d1=-0.03)
    assert "逆勢抗跌" not in tag(_row(d1=-0.01), market_d1=0.0)


def test_tag_marks_abnormal_pe():
    assert "⚠PE異常" in tag(_row(pe_ratio=450.0), market_d1=0.0)
    assert "⚠PE異常" in tag(_row(pe_ratio=-5.0), market_d1=0.0)
    assert "⚠PE異常" not in tag(_row(pe_ratio=15.0), market_d1=0.0)


def test_hi60_prior_excludes_recent_five_bars():
    """突破基準必須是**不含最近 5 天**的 60 日高——含最近 5 天的話今天必然是自己的高點。"""
    g = _bars([100.0] * 80)
    g.loc[g.index[-3], "high"] = 999.0            # 最近 3 天內的極高點不該進基準
    f = compute_factors(g)
    assert f["hi60_prior"] < 999.0
    # break_pct 以 hi60_prior 為分母
    assert f["break_pct"] == pytest.approx(f["close"] / f["hi60_prior"] - 1)


def test_vol_ratio5_is_five_over_sixty_day_average():
    g = _bars([100.0] * 80)
    g["volume"] = [1000.0] * 75 + [3000.0] * 5     # 最近 5 天量放大
    f = compute_factors(g)
    assert f["vol_ratio5"] > 2.0


def test_breakout_funnel_applies_volume_upper_bound():
    """量比有上限：四個分位單調遞減（1.3~1.5 命中 24.1% → >3 只有 18.1%），爆量是力竭。"""
    from screen_tw import BREAKOUT, funnel
    base = {
        "is_etf": False, "is_tib": False, "turnover20": 5e8, "close": 110.0,
        "hi60_prior": 100.0, "d5": 0.10, "yoy": 30.0, "pe_ratio": 15.0,
        "d1": 0.01, "d20": 0.10, "bias20": 0.05, "inst_5": 1.0,
    }
    df = pd.DataFrame([
        {**base, "stock_id": "1101", "vol_ratio5": 1.5},   # 在區間內
        {**base, "stock_id": "1102", "vol_ratio5": 5.0},   # 爆量,應被剔除
        {**base, "stock_id": "1103", "vol_ratio5": 1.0},   # 量能不足,應被剔除
    ])
    pool, steps = funnel(df, 2e8, "breakout")
    assert list(pool["stock_id"]) == ["1101"]
    assert BREAKOUT["vol_ratio5_max"] == 2.0


def test_momentum_score_survives_a_stale_valuation_table():
    """估值缺日不能讓整個 score 變 NaN——那會讓 `--top N` 靜默退化成「代號最小的 N 檔」。

    `valuation` 走 `BWIBBU_ALL`（無日期參數的當日快照），官方常盤後才發布，所以
    `date = as_of` 查到 0 列是常態；左 join 後 `pe_ratio` 整欄 NaN，而舊版
    `fillna(median())` 的 median 自己也是 NaN → rank 全 NaN → score 全 NaN。
    實測 2026-07-30 momentum 寬掃 5 檔全是 score=None、順序 1101/1102/1216/1402/1476。
    """
    from screen_tw import funnel
    base = {
        "is_etf": False, "is_tib": False, "turnover20": 5e8, "close": 110.0,
        "ma20": 105.0, "ma60": 100.0, "inst_5": 1.0, "bias20": 0.05,
        "hi60_prior": 100.0, "d5": 0.10, "vol_ratio5": 1.5, "yoy": 30.0,
        "pe_ratio": float("nan"),                      # 估值整欄缺
    }
    df = pd.DataFrame([
        {**base, "stock_id": "9999", "d20": 0.30, "d1": 0.03},   # 動能最強、代號最大
        {**base, "stock_id": "1101", "d20": 0.05, "d1": 0.00},   # 動能最弱、代號最小
    ])

    pool, _ = funnel(df, 2e8, "momentum")

    assert pool["score"].notna().all(), "估值缺日時 score 不得為 NaN"
    # 排序必須由其餘四項決定，不能退回代號序
    assert list(pool["stock_id"]) == ["9999", "1101"]


def test_pe_score_is_neutral_only_when_every_value_is_missing():
    from screen_tw import _pe_score

    allnan = _pe_score(pd.Series([float("nan")] * 3))
    assert (allnan == 0.5).all()
    # 有可用值時仍要低本益比得高分（且部分缺值走 median 補）
    partial = _pe_score(pd.Series([10.0, 50.0, float("nan")]))
    assert partial.iloc[0] > partial.iloc[1]
    assert partial.notna().all()


def test_breakout_funnel_requires_revenue_growth():
    """營收條件是唯一讓前瞻分布歪向右邊的東西——純價格突破是 16.4% 上 / 16.5% 下。"""
    from screen_tw import funnel
    base = {
        "is_etf": False, "is_tib": False, "turnover20": 5e8, "close": 110.0,
        "hi60_prior": 100.0, "d5": 0.10, "vol_ratio5": 1.5, "pe_ratio": 15.0,
        "d1": 0.01, "d20": 0.10, "bias20": 0.05, "inst_5": 1.0,
    }
    df = pd.DataFrame([
        {**base, "stock_id": "1101", "yoy": 25.0},
        {**base, "stock_id": "1102", "yoy": 5.0},
        {**base, "stock_id": "1103", "yoy": float("nan")},   # 上櫃無月營收 → 篩掉
    ])
    pool, _ = funnel(df, 2e8, "breakout")
    assert list(pool["stock_id"]) == ["1101"]


# ---- 研究宇宙：live 漏斗與量測腳本共用 `is_common_stock` -------------------------------
# 量測端（measure_signal_forward）只收四位數普通股、排除 ETF 00xx／TDR 91xx；live 原本只排 00
# 開頭，TDR（9105、912000 在 monthly_revenue 都有資料）能進候選池，但錨點母體裡沒有它。


@pytest.mark.parametrize("sid", ["9105", "912000", "00878", "0050", "00631L", "2887A", "020039", "70001"])
def test_universe_predicate_rejects_non_common_stock(sid):
    from market_data.adjust import is_common_stock
    assert not is_common_stock(sid)


@pytest.mark.parametrize("sid", ["2330", "9921", "9904", "9802", "6488", "5305"])
def test_universe_predicate_keeps_four_digit_common_stock_including_9xxx(sid):
    """反向檢查：9 開頭的普通股（巨大、寶成）不能被「排除所有 9xxx」的過度修法誤殺。"""
    from market_data.adjust import is_common_stock
    assert is_common_stock(sid)


def test_funnel_uses_the_same_universe_as_the_forward_measurement():
    from screen_tw import funnel
    base = {
        "is_tib": False, "turnover20": 5e8, "close": 110.0,
        "hi60_prior": 100.0, "d5": 0.10, "vol_ratio5": 1.5, "yoy": 30.0, "pe_ratio": 15.0,
        "d1": 0.01, "d20": 0.10, "bias20": 0.05, "inst_5": 1.0,
    }
    sids = ["2330", "9105", "912000", "00878", "00631L", "2887A", "9921"]
    # is_etf 照 build() 的寫法給（只看 00 開頭）：漏斗若退回 `~is_etf`，TDR 與特別股就會漏進來
    df = pd.DataFrame([{**base, "stock_id": s, "is_etf": s.startswith("00")} for s in sids])
    for strategy in ("breakout", "momentum"):
        pool, steps = funnel(df.assign(ma20=105.0, ma60=100.0), 2e8, strategy)
        assert sorted(pool["stock_id"]) == ["2330", "9921"], strategy
        assert steps["排除 ETF／TDR／非普通股與創新板"] == 2


@pytest.mark.parametrize("strategy", ["breakout", "momentum"])
def test_funnel_routes_every_code_through_the_shared_predicate(strategy, monkeypatch):
    """漏斗必須逐檔呼叫 `screen_tw.is_common_stock`（同一個 seam），不能另寫一份前綴規則。"""
    from market_data.adjust import is_common_stock

    accepted = {"2330", "6488", "5305", "9802", "9904", "9921"}
    codes = [*sorted(accepted), "9105", "912000", "00878", "0050", "00631L",
             "2887A", "70001", "7610"]
    base = {
        "turnover20": 5e8, "close": 110.0, "ma20": 105.0, "ma60": 100.0,
        "hi60_prior": 100.0, "d5": 0.1, "vol_ratio5": 1.5, "yoy": 30.0,
        "inst_5": 1.0, "d20": 0.1, "d1": 0.01, "bias20": 0.05, "pe_ratio": 15.0,
    }
    df = pd.DataFrame([
        {**base, "stock_id": sid, "is_etf": sid.startswith("00"), "is_tib": sid == "7610"}
        for sid in codes
    ])
    seen = []

    def checked(sid):
        seen.append(sid)
        return is_common_stock(sid)

    # 先釘住腳本綁的就是共用謂詞；否則下面的 spy 會蓋掉錯誤的本地綁定，守門形同虛設。
    assert screen_tw.is_common_stock is is_common_stock
    monkeypatch.setattr(screen_tw, "is_common_stock", checked)
    pool, steps = screen_tw.funnel(df, 2e8, strategy)

    assert set(pool["stock_id"]) == accepted
    assert seen == codes
    assert list(steps.values())[:2] == [len(codes), len(accepted)]


# ---- 上櫃月營收的口徑閘門 ---------------------------------------------------------------
# `monthly_revenue` 自 2026-09 起也收上櫃。live 漏斗與三支量測腳本必須**同一個口徑**：
# 只閘 live 會讓基準數字量的是另一個池子，只閘量測則讓 live 下單的池子沒被量過。

import screen_tw  # noqa: E402


def _seed(tmp_path, monkeypatch):
    seed = tmp_path / "stock_list_tw.csv"
    seed.write_text("ts_code,symbol,name,enname,aliases\n"
                    "1101.TW,1101.TW,台泥,,\n6488.TWO,6488.TWO,環球晶,,\n", encoding="utf-8")
    monkeypatch.setattr(screen_tw, "SEED_CSV", seed)


def test_exclude_otc_revenue_keeps_listed_and_delisted_rows(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    rev = pd.DataFrame({"stock_id": ["1101", "6488", "5305"], "yoy": [25.0, 40.0, 30.0]})
    # 5305 不在種子檔（已下市）→ 由 revenue-pit 補的列照舊保留，池子與修改前逐列相同
    assert screen_tw.exclude_otc_revenue(rev)["stock_id"].tolist() == ["1101", "5305"]


def test_exclude_otc_revenue_refuses_to_guess_without_the_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(screen_tw, "SEED_CSV", tmp_path / "missing.csv")
    with pytest.raises(FileNotFoundError):
        screen_tw.exclude_otc_revenue(pd.DataFrame({"stock_id": ["1101"], "yoy": [1.0]}))


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *a, **k):
        class _R:
            def scalar(self):
                return pd.Timestamp("2026-08-03")
        return _R()


class _Eng:
    def connect(self):
        return _Conn()


def _fake_read_sql(sql, conn, params=None, parse_dates=None):
    q = str(sql)
    days = pd.date_range("2026-07-01", "2026-08-03", freq="D")
    if "market.price" in q:
        return pd.DataFrame([{"stock_id": s, "date": d, "open": 10.0, "high": 10.0, "low": 10.0,
                              "close": 10.0, "volume": 1.0, "turnover": 1.0, "pe_ratio": 1.0}
                             for s in ("1101", "6488") for d in days])
    if "market.monthly_revenue" in q:
        return pd.DataFrame({"stock_id": ["1101", "6488"],
                             "date": [pd.Timestamp("2026-07-10")] * 2,
                             "announce_date": [pd.Timestamp("2026-07-10")] * 2,
                             "revenue_month": [pd.Timestamp("2026-06-01")] * 2,
                             "yoy": [25.0, 40.0], "mom": [1.0, 1.0]})
    return pd.DataFrame({"stock_id": [], "date": []})


def _run_loader(name, monkeypatch, include):
    monkeypatch.setattr(pd, "read_sql", _fake_read_sql)
    factors = lambda eng, idx, cols: pd.DataFrame(2.0, index=idx, columns=cols)  # noqa: E731
    if name == "screen_tw":
        monkeypatch.setattr(screen_tw, "load_factors", factors)
        return screen_tw.load(_Eng(), None, include)[5]
    if name == "measure":
        import measure_signal_forward as m
        monkeypatch.setattr(m, "load_factors", factors)
        return m.load(_Eng(), "2026-07-01", "2026-08-03", include)[1]
    import backtest_screen as b
    monkeypatch.setattr(b, "load_factors", factors)
    return b.load_panel(_Eng(), "2026-07-01", "2026-08-03", include)[3]


@pytest.mark.parametrize("loader", ["screen_tw", "measure", "backtest"])
def test_every_revenue_loader_defaults_to_listed_only(loader, tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert set(_run_loader(loader, monkeypatch, False)["stock_id"]) == {"1101"}
    # 反向：旗標要真的把上櫃放回來，否則「預設排除」其實是「永遠排除」
    assert set(_run_loader(loader, monkeypatch, True)["stock_id"]) == {"1101", "6488"}


def test_json_withholds_the_listed_base_rate_when_otc_revenue_is_included():
    pool = pd.DataFrame(columns=["stock_id", "industry"])
    listed = screen_tw.to_json(pd.Timestamp("2026-08-03"), pool, {}, 0.0, "breakout", 5)
    mixed = screen_tw.to_json(pd.Timestamp("2026-08-03"), pool, {}, 0.0, "breakout", 5,
                              include_otc_revenue=True)
    assert listed["measured_base_rate"]["p_close60_up_30pct"] == 0.202
    # 20.2% 是上市口徑量的錨點；池子換了還交給 agent，等於讓 confidence 錨在別的分布上
    assert mixed["measured_base_rate"] is None
    assert "measure_signal_forward.py" in " ".join(mixed["blind_spots"])


# ---- 揭露：範圍、實際資料日、缺值、60 日高、估值挑日 -------------------------------------
# 法人／融資／估值上櫃可能尚未回補；18:00 時法人與融資常停在前一天。這些都是「數字看起來完整其實不是」
# 的類型，所以報告必須自己講出來，而且缺值不能印成 nan。

AS_OF = pd.Timestamp("2026-10-16")


def _pool_row(sid="1101", **kw):
    base = {
        "stock_id": sid, "name": "台泥", "industry": "01", "close": 90.0, "break_pct": 0.05,
        "vol_ratio5": 1.5, "vol_ratio": 1.0, "d1": 0.01, "d5": 0.06, "d20": 0.10, "d60": 0.2,
        "bias20": 0.05, "rsi14": 60.0, "turnover20": 5e8, "inst_5": 2000.0, "inst_streak": 3.0,
        "pe_ratio": 15.0, "pb_ratio": 1.2, "dividend_yield": 3.0, "yoy": 30.0,
        "margin_chg5": 0.0, "from_hi60": -0.10, "ma5": 89.0, "ma10": 88.0, "ma20": 87.0,
        "ma60": 80.0, "atr_pct": 0.02, "is_etf": False,
    }
    return {**base, **kw}


def _render(rows, freshness=None):
    pool = pd.DataFrame(rows)
    return screen_tw.render(AS_OF, pool, pool, {}, 0.0, pd.DataFrame(), 25, 2.0,
                            freshness=freshness)


def _cells(md, sid, header_prefix):
    """取出表格中 sid 那一列，依該表標題列對齊欄名 → {欄名: 內容}。"""
    lines = md.splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.startswith(header_prefix))
    names = [c.strip() for c in lines[head].strip("|").split("|")]
    row = next(ln for ln in lines[head + 2:] if f"| {sid} |" in ln)
    return dict(zip(names, [c.strip() for c in row.strip("|").split("|")]))


def test_render_prints_dash_for_nan_chip_cells_but_keeps_zero():
    """上櫃的法人欄是 NaN → 印「—」而不是 `nan張 nan天`；真的 0 要照印，不能和缺值混在一起。"""
    md = _render([_pool_row("6488", inst_5=float("nan"), inst_streak=float("nan")),
                  _pool_row("1101", inst_5=0.0, inst_streak=0.0)])
    assert "nan" not in md.lower()
    otc = _cells(md, "6488", "| # | 代碼")
    assert otc["法人5日"] == "—" and otc["連買"] == "—"
    listed = _cells(md, "1101", "| # | 代碼")
    assert listed["法人5日"] == "+0張" and listed["連買"] == "0天"


def test_reference_table_labels_the_sixty_day_high():
    """欄位用 `from_hi60` 反推，本來就是 60 日高；標成「20日高」會讓 agent 拿來當 20 日壓力。"""
    md = _render([_pool_row(close=90.0, from_hi60=-0.10)])
    assert "60日高" in md and "20日高" not in md
    assert _cells(md, "1101", "| 代碼 | 名稱")["60日高"] == "100.00"


def test_render_and_json_state_the_listed_only_scope():
    md = _render([_pool_row()])
    assert screen_tw.LISTED_ONLY_NOTE in md
    assert "上市" in screen_tw.LISTED_ONLY_NOTE and "上櫃" in screen_tw.LISTED_ONLY_NOTE
    assert "momentum" in screen_tw.LISTED_ONLY_NOTE
    out = screen_tw.to_json(AS_OF, pd.DataFrame(columns=["stock_id", "industry"]), {}, 0.0,
                            "breakout", 5)
    assert screen_tw.LISTED_ONLY_NOTE in out["blind_spots"]


def _fresh(inst_last="2026-10-16", inst_n=5, margin_last="2026-10-16", margin_n=5,
           val_date="2026-10-16"):
    ts = lambda v: pd.Timestamp(v) if v else None  # noqa: E731
    return {"inst_last": ts(inst_last), "inst_sessions": inst_n, "margin_last": ts(margin_last),
            "margin_sessions": margin_n, "val_date": ts(val_date)}


def test_render_flags_chip_tables_that_lag_the_base_date():
    fresh = _fresh(inst_last="2026-10-15", inst_n=4, margin_last="2026-10-14", margin_n=3,
                   val_date="2026-10-15")
    md = _render([_pool_row()], fresh)
    assert "法人最新到 2026-10-15" in md and "5 日統計實際涵蓋 4 個場次" in md
    assert "融資最新到 2026-10-14" in md and "5 日統計實際涵蓋 3 個場次" in md
    assert "估值取 2026-10-15" in md
    out = screen_tw.to_json(AS_OF, pd.DataFrame(columns=["stock_id", "industry"]), {}, 0.0,
                            "breakout", 5, freshness=fresh)
    assert any("法人最新到 2026-10-15" in b for b in out["blind_spots"])


def test_render_is_quiet_when_every_table_is_on_the_base_date():
    """同日不出落後標註，否則每份報告都帶一排沒有資訊的警告，真正落後時就看不出來。"""
    md = _render([_pool_row()], _fresh())
    assert "最新到" not in md and "估值取" not in md
    assert "估值日：**2026-10-16**" in md          # 估值日本身一律印出


def test_render_states_when_there_is_no_chip_or_valuation_data_at_all():
    md = _render([_pool_row()], _fresh(inst_last=None, inst_n=0, margin_last=None, margin_n=0,
                                       val_date=None))
    assert "法人無資料" in md and "融資無資料" in md and "內無資料" in md


def _px_dates(n=8):
    days = pd.bdate_range(end=AS_OF, periods=n)
    return pd.DataFrame({"date": days, "stock_id": "1101"})


def _tbl(dates, col):
    return pd.DataFrame({"stock_id": "1101", "date": pd.to_datetime(list(dates)), col: 1.0})


def test_data_freshness_counts_sessions_actually_present():
    """18:00 時法人／融資只到前一天：近 5 日統計實際只有 4 個場次。"""
    px = _px_dates()
    d = list(px["date"])
    full = screen_tw.data_freshness(px, _tbl(d, "foreign_net"), _tbl(d, "margin_balance"),
                                    pd.DataFrame())
    assert full["inst_last"] == AS_OF and full["inst_sessions"] == 5
    assert full["margin_last"] == AS_OF and full["margin_sessions"] == 5
    assert full["val_date"] is None
    lag = screen_tw.data_freshness(px, _tbl(d[:-1], "foreign_net"), _tbl(d[:-1], "margin_balance"),
                                   pd.DataFrame({"stock_id": ["1101"], "date": [d[-2]]}))
    assert lag["inst_last"] == d[-2] and lag["inst_sessions"] == 4
    assert lag["margin_last"] == d[-2] and lag["margin_sessions"] == 4
    assert lag["val_date"] == d[-2]


def _valuation_rows():
    # 基準日 2026-08-03；窗口是 (07-27, 08-03]，所以 07-26 以前算太舊
    return pd.DataFrame([
        {"stock_id": s, "date": pd.Timestamp(d), "pe_ratio": pe, "pb_ratio": 1.0,
         "dividend_yield": 2.0}
        for d, pe in (("2026-07-20", 99.0), ("2026-07-30", 12.0), ("2026-07-31", 13.0))
        for s in ("1101", "1102")
    ])


def _load_valuation(monkeypatch, tmp_path, rows):
    """用假 read_sql 重現估值表的 where：套用呼叫端傳進去的 d／lo 兩個界線。"""
    _seed(tmp_path, monkeypatch)
    seen = {}

    def fake(sql, conn, params=None, parse_dates=None):
        if "market.valuation" in str(sql):
            seen.update(params or {})
            seen["sql"] = " ".join(str(sql).split())
            out = rows[rows["date"] <= pd.Timestamp(params["d"])]
            if "lo" in params:
                out = out[out["date"] > pd.Timestamp(params["lo"])]
            return out.reset_index(drop=True)
        return _fake_read_sql(sql, conn, params, parse_dates)

    monkeypatch.setattr(pd, "read_sql", fake)
    monkeypatch.setattr(screen_tw, "load_factors",
                        lambda eng, idx, cols: pd.DataFrame(2.0, index=idx, columns=cols))
    val = screen_tw.load(_Eng(), pd.Timestamp("2026-08-03"))[4]
    return val, seen


def test_valuation_takes_the_latest_day_within_seven_calendar_days(monkeypatch, tmp_path):
    val, seen = _load_valuation(monkeypatch, tmp_path, _valuation_rows())
    assert set(val["date"]) == {pd.Timestamp("2026-07-31")}   # 整包同一天，不混日期
    assert len(val) == 2 and set(val["pe_ratio"]) == {13.0}
    assert pd.Timestamp(seen["lo"]) == pd.Timestamp("2026-07-27")   # 7 曆日窗口的下界
    # 假 read_sql 靠參數過濾；SQL 本身也得真的用到這兩個界線，且不能退回 `date = :d`
    assert "date <= :d" in seen["sql"] and "date > :lo" in seen["sql"]
    assert "date = :d" not in seen["sql"]


@pytest.mark.parametrize("twse_day,tpex_day", [("2026-07-31", "2026-07-30"), ("2026-07-30", "2026-07-31")])
def test_valuation_latest_day_is_picked_per_market(monkeypatch, tmp_path, twse_day, tpex_day):
    # 上市與上櫃發布日差一天時，兩邊都要留下各自最新那天，不能被另一邊的日期整包剔除
    rows = pd.DataFrame([
        {"stock_id": s, "date": pd.Timestamp(d), "market": m, "pe_ratio": pe, "pb_ratio": 1.0,
         "dividend_yield": 2.0}
        for s, m, days in (("1101", None, (twse_day, "2026-07-29")), ("6488", "tpex", (tpex_day, "2026-07-29")))
        for d, pe in zip(days, (13.0, 99.0))
    ])
    val, _ = _load_valuation(monkeypatch, tmp_path, rows)
    got = dict(zip(val["stock_id"], val["date"]))
    assert got == {"1101": pd.Timestamp(twse_day), "6488": pd.Timestamp(tpex_day)}
    assert set(val["pe_ratio"]) == {13.0} and "market" not in val.columns


def test_valuation_older_than_the_window_is_not_used(monkeypatch, tmp_path):
    """窗口只有 07-20 一天（遠超 7 日）→ 寧可整欄「—」，不拿十幾天前的 PE 當今天的。"""
    old = _valuation_rows()
    old = old[old["date"] == pd.Timestamp("2026-07-20")]
    val, _ = _load_valuation(monkeypatch, tmp_path, old)
    assert val.empty
    fresh = screen_tw.data_freshness(_px_dates(), pd.DataFrame(), pd.DataFrame(), val)
    assert fresh["val_date"] is None


def test_build_does_not_leak_the_valuation_date_column():
    """val 新增 date 欄供挑日，merge 進 df 時不能多出一欄 date 汙染下游。"""
    px = _bars([100.0 + i for i in range(80)]).assign(stock_id="1101")
    px["date"] = pd.bdate_range(end=AS_OF, periods=80)
    inst = pd.DataFrame({"stock_id": ["1101"], "date": [AS_OF], "foreign_net": [1.0],
                         "trust_net": [1.0], "dealer_net": [1.0]})
    mgn = pd.DataFrame({"stock_id": ["1101"], "date": [AS_OF], "margin_balance": [10.0]})
    val = pd.DataFrame({"stock_id": ["1101"], "date": [AS_OF], "pe_ratio": [12.0],
                        "pb_ratio": [1.0], "dividend_yield": [3.0]})
    rev = pd.DataFrame({"stock_id": ["1101"], "revenue_month": [AS_OF], "yoy": [1.0], "mom": [1.0]})
    info = pd.DataFrame({"stock_id": ["1101"], "name": ["台泥"], "industry": ["01"]})
    idx = pd.DataFrame({"date": [AS_OF], "close": [100.0], "change": [1.0]})
    df, _ = screen_tw.build(AS_OF, px, inst, mgn, val, rev, info, idx, 0.0)
    assert "date" not in df.columns and df.loc[0, "pe_ratio"] == 12.0


# ---- 即時官方名單：處置／注意股旗標、事件日曆 -----------------------------------------------
# `live=None`（預設）時 render／to_json 必須和接上即時名單之前**逐字相同**——fixture 是改動前
# 的程式產生的（見 `tests/screen_tw_baseline_inputs.py`），不能拿新版輸出回填。

import datetime as _dt  # noqa: E402
import re  # noqa: E402

from market_data import events as _events  # noqa: E402
from market_data.risk_flags import RiskHit  # noqa: E402
from market_data.tw_official_http import SourceStatus  # noqa: E402

from tests import screen_tw_baseline_inputs as _baseline  # noqa: E402

_BASELINE_DIR = Path(__file__).resolve().parent / "fixtures" / _baseline.FIXTURE_DIR_NAME


def test_render_without_live_is_byte_identical_to_the_pre_change_output():
    assert _baseline.render_baseline(screen_tw) == (_BASELINE_DIR / "render.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("strategy", ["breakout", "momentum"])
def test_json_without_live_is_byte_identical_to_the_pre_change_output(strategy):
    expected = (_BASELINE_DIR / f"to_json_{strategy}.json").read_text(encoding="utf-8")
    assert _baseline.json_baseline(screen_tw, strategy) == expected


@pytest.mark.parametrize("flag, label", [("處置中", "⚠處置中"), ("即將處置", "⚠即將處置"),
                                         ("注意股", "⚠注意股")])
def test_tag_marks_risk_flags(flag, label):
    assert label in tag(pd.Series(_row(risk_flag=flag)), 0.0)


@pytest.mark.parametrize("flag", [None, ""])
def test_tag_is_silent_for_unchecked_and_clean(flag):
    assert not any("處置" in t or "注意" in t for t in tag(pd.Series(_row(risk_flag=flag)), 0.0))


_LIVE_AS_OF = pd.Timestamp("2026-10-20")
_NEXT = _dt.date(2026, 10, 21)
_OK4 = [SourceStatus("上市處置", True, "資訊更新 10/20"), SourceStatus("上市注意", True, "14 列皆為 10/20"),
        SourceStatus("上櫃注意", True, "19 列皆為 10/20"), SourceStatus("上櫃處置", True, "新鮮度旁證")]
_TPEX_DOWN = _OK4[:2] + [SourceStatus("上櫃注意", False, "空回應無法證明新鮮"),
                         SourceStatus("上櫃處置", False, "無法證明新鮮")]


def _risk(statuses=_OK4, flags=None):
    flags = flags if flags is not None else {"2424": RiskHit("處置中", "隴華", "處置中 10/21～10/28，人工管制撮合")}
    return screen_tw.RiskResult(flags, list(statuses), _NEXT)


def _skip(reason, opted_out=False):
    return screen_tw.Skipped(reason, opted_out, 5)


def test_apply_risk_flags_uses_the_seed_market_when_price_market_is_null():
    """實際 DB 的 price.market 全為 NULL：市場別必須從種子檔來，否則旗標永遠是「未經檢查」。"""
    df = pd.DataFrame([_pool_row("1101", market=None), _pool_row("6488", market=None),
                       _pool_row("2424", market=None), _pool_row("5305", market=None)])
    seed = {"1101": "twse", "6488": "tpex", "2424": "twse"}   # 5305 已下市、不在種子檔

    out = screen_tw.apply_risk_flags(df, _risk(_TPEX_DOWN), market_map=seed)

    flags = dict(zip(out["stock_id"], out["risk_flag"]))
    assert flags["1101"] == ""            # 上市兩份名單都可用、不在名單 → 查過、乾淨
    assert flags["6488"] is None          # 上櫃名單不可用 → 未經檢查
    assert flags["2424"] == "處置中"
    assert flags["5305"] is None          # 市場未知 → 未經檢查
    assert list(out["market"]) == ["twse", "tpex", "twse", None]


def test_apply_risk_flags_reads_the_seed_csv(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    df = pd.DataFrame([_pool_row("1101"), _pool_row("6488")])

    out = screen_tw.apply_risk_flags(df, _risk(_TPEX_DOWN, flags={}))

    assert list(out["risk_flag"]) == ["", None]


def test_apply_risk_flags_when_skipped_leaves_everything_unchecked():
    df = pd.DataFrame([_pool_row("1101")])
    out = screen_tw.apply_risk_flags(df, _skip(screen_tw.SKIP_HISTORICAL, True), market_map={"1101": "twse"})
    assert out["risk_flag"].tolist() == [None]


_WINDOW = _events.EventWindow(_dt.date(2026, 10, 21), _dt.date(2026, 10, 27), _dt.date(2026, 10, 19), 5)
_MOPS_SII_OK = SourceStatus(_events.SRC_MOPS_SII, True, _events.MOPS_NOTE, proven=False)


def _ev(by_stock=None, statuses=None, revenue=()):
    by_stock = by_stock if by_stock is not None else {
        "1101": [_events.Event("1101", _events.CONFERENCE, _dt.date(2026, 10, 23), _dt.date(2026, 10, 23),
                               "第三季財務報告", "MOPS", "14:00"),
                 _events.Event("1101", "除息", _dt.date(2026, 10, 26), _dt.date(2026, 10, 26),
                               "", "TWT48U", cash=1.5)],
        "6488": [_events.Event("6488", _events.FORUM, _dt.date(2026, 10, 21), _dt.date(2026, 10, 22),
                               "受邀參加", "MOPS", "09:00")],
    }
    statuses = statuses if statuses is not None else [
        _MOPS_SII_OK,
        SourceStatus(_events.SRC_TWT48U, False, "拒收：Last-Modified 10/15，超過 1 個交易日未更新")]
    return screen_tw.EventsResult(_WINDOW, by_stock, statuses, list(revenue))


def _live_render(rows, live):
    pool = pd.DataFrame(rows)
    return screen_tw.render(_LIVE_AS_OF, pool, pool, {}, 0.0, pd.DataFrame(), 25, 2.0, live=live)


def _flagged_rows():
    return [_pool_row("2424", name="隴華", risk_flag="處置中", risk_flag_detail="處置中 10/21～10/28，人工管制撮合"),
            _pool_row("1101", risk_flag=""), _pool_row("6488", name="環球晶", risk_flag=None)]


def test_render_lists_flagged_and_unchecked_candidates_but_never_zero():
    md = _live_render(_flagged_rows(), {"risk": _risk(_TPEX_DOWN), "events": _ev()})

    assert "### ⚠ 處置／注意股（1 檔" in md and "- 2424 隴華（處置中 10/21～10/28，人工管制撮合）" in md
    assert "### ⚠ 處置／注意股名單未取得：上櫃注意（空回應無法證明新鮮）、上櫃處置（無法證明新鮮）" in md
    assert "以下候選未經檢查，不代表沒有：6488 環球晶" in md
    assert not re.search(r"0 檔(處置|注意)|處置股 0|無處置", md)
    assert "- 處置／注意股名單：上市處置 ✓（資訊更新 10/20）、上市注意 ✓（14 列皆為 10/20）、上櫃注意 ✗" in md


def test_render_with_all_lists_clean_prints_no_risk_section_and_no_zero_claim():
    md = _live_render([_pool_row("1101", risk_flag="")], {"risk": _risk(flags={}), "events": _ev({})})
    assert "處置／注意股（" not in md and "名單未取得" not in md
    assert not re.search(r"0 檔(處置|注意)|處置股 0|無處置", md)


def test_render_opted_out_risk_flags_only_says_why_in_the_status_line():
    """使用者自己關掉（--no-risk-flags／--date）：§0 一行原因就夠了，不逐檔列「未經檢查」。"""
    for reason in (screen_tw.SKIP_HISTORICAL, "--no-risk-flags"):
        md = _live_render([_pool_row("1101", risk_flag=None)],
                          {"risk": _skip(reason, opted_out=True), "events": _skip(reason, opted_out=True)})
        assert f"- 處置／注意股名單：未查（{reason}）" in md
        assert "名單未取得" not in md and "以下候選未經檢查" not in md


@pytest.mark.parametrize("reason", [screen_tw.SKIP_CALENDAR, "基準日 2026-10-20 不是預期場次 2026-10-21",
                                    "抓取時發生例外（RuntimeError: x）"])
def test_render_lists_unchecked_candidates_when_the_fetch_was_wanted_but_not_done(reason):
    """反向：想抓卻沒抓成（日曆不可用、DB 落後、例外）仍要逐檔列出「未經檢查」與人工連結。"""
    md = _live_render([_pool_row("1101", risk_flag=None)],
                      {"risk": _skip(reason), "events": _skip(reason)})
    assert f"### ⚠ 處置／注意股名單未取得：{reason}" in md
    assert "以下候選未經檢查，不代表沒有：1101 台泥" in md


def test_render_event_calendar_replaces_the_hard_coded_reminder():
    md = _live_render([_pool_row("1101"), _pool_row("6488", name="環球晶"), _pool_row("3105", name="穩懋")],
                      {"risk": _risk(), "events": _ev(statuses=[
                          _MOPS_SII_OK,
                          SourceStatus(_events.SRC_TWT48U, False, "拒收：Last-Modified 10/15，超過 1 個交易日未更新"),
                          SourceStatus(_events.SRC_TPEX_EX, True, "資料時間 10/20")],
                          revenue=[_dt.date(2026, 11, 10)])})

    assert "未來 5 個交易日的事件**：FOMC、美國科技巨頭財報、台廠法說" not in md
    assert "2. **未來 5 個交易日的事件**：FOMC、美國科技巨頭財報仍需自行查；台廠法說／除權息／月營收期限見下方「事件日曆」" in md
    assert "### 事件日曆（未來 5 個交易日，10/21~10/27）" in md
    assert "- **1101 台泥**：法說 10/23 14:00（自辦）　除息 10/26（現金 1.5 元）" in md
    assert "- **6488 環球晶**：法說 10/21~10/22（券商論壇或未明）" in md
    assert "- 月營收：窗口與 11/01~11/10 公告期重疊（期限 11/10" in md
    assert "- 來源：法說會（上市 MOPS） 可用（未證明新鮮）：MOPS 表上沒有資料日期" in md
    assert "- 來源：除權息預告（上市 TWT48U） 不可用：拒收" in md
    assert "3105" not in md.split("### 事件日曆")[1].split("### 逐檔查")[0]   # 沒命中的不列
    assert "無事件" not in md and not re.search(r"0 檔(事件|法說)", md)
    # 逐檔查：自辦法說／除權息才追問，論壇不追問
    assert "5 個交易日內有法說／除息（10/23、10/26），事件前是否降部位？" in md
    assert "5 個交易日內有論壇" not in md


def test_render_event_calendar_without_hits_still_shows_sources():
    md = _live_render([_pool_row("1101")], {"risk": _risk(), "events": _ev({})})
    assert "- 前 25 名在可用來源中未見事件（未列不代表沒有，見下方來源狀態）" in md
    assert "- 來源：法說會（上市 MOPS）" in md


def test_render_keeps_the_reminder_and_says_why_when_events_were_skipped():
    md = _live_render([_pool_row("1101")], {"risk": _risk(), "events": _skip(screen_tw.SKIP_CALENDAR)})
    assert ("2. **未來 5 個交易日的事件**：FOMC、美國科技巨頭財報、台廠法說、月營收公布日、除權息"
            f"（本報告未附事件日曆：{screen_tw.SKIP_CALENDAR}）") in md
    assert "### 事件日曆" not in md


def test_json_carries_live_fields_and_blind_spots():
    pool = pd.DataFrame(_flagged_rows())
    out = screen_tw.to_json(_LIVE_AS_OF, pool, {}, 0.0, "breakout", 5,
                            live={"risk": _risk(_TPEX_DOWN), "events": _ev()})

    recs = {r["stock_id"]: r for r in out["candidates"]}
    assert recs["2424"]["risk_flag"] == "處置中" and "⚠處置中" in recs["2424"]["tags"]
    assert recs["1101"]["risk_flag"] == "" and recs["6488"]["risk_flag"] is None
    # 2424 沒有市場別（列上無 market 欄）→ 事件也是未經檢查；1101 有命中照列
    assert recs["2424"]["events"] is None and recs["1101"]["events"][0]["kind"] == "法說"
    assert out["revenue_deadlines"] == []
    assert out["next_session"] == "2026-10-21" and out["risk_flag_skipped"] is None
    assert [s["name"] for s in out["risk_flag_sources"]][2] == "上櫃注意"
    assert out["event_window"] == {"n": 5, "start": "2026-10-21", "end": "2026-10-27"}
    blind = " ".join(out["blind_spots"])
    assert "上櫃注意 不可用" in blind and "除權息預告（上市 TWT48U） 不可用" in blind
    assert "法說會（上市 MOPS） 可用但未證明新鮮" in blind


def test_json_marks_everything_unchecked_when_skipped():
    pool = pd.DataFrame([_pool_row("1101")])
    out = screen_tw.to_json(_LIVE_AS_OF, pool, {}, 0.0, "breakout", 5,
                            live={"risk": _skip("--no-risk-flags", True), "events": _skip("--no-events", True)})
    rec = out["candidates"][0]
    assert rec["risk_flag"] is None and rec["events"] is None
    assert out["risk_flag_skipped"] == "--no-risk-flags" and out["event_window"] is None
    assert out["revenue_deadlines"] is None   # 沒抓就沒算過窗口：null＝未經檢查，不是 []
    assert any("未經檢查" in b for b in out["blind_spots"])


_EV_OK4 = [SourceStatus(name, True, "") for name in _events.SOURCE_MARKET]


def _ev_statuses(failed=()):
    return [SourceStatus(s.name, s.name not in failed, "連線失敗" if s.name in failed else "")
            for s in _EV_OK4]


def _events_by_sid(statuses, by_stock=None):
    rows = [_pool_row("1101", market="twse"), _pool_row("6488", name="環球晶", market="tpex"),
            _pool_row("2330", name="台積電", market="twse"), _pool_row("5305", name="敦南", market=None)]
    by_stock = by_stock if by_stock is not None else {}
    out = screen_tw.to_json(_LIVE_AS_OF, pd.DataFrame(rows), {}, 0.0, "breakout", 5,
                            live={"risk": _risk(), "events": _ev(by_stock, statuses)})
    return {r["stock_id"]: r["events"] for r in out["candidates"]}


def test_json_events_are_unchecked_when_every_event_source_failed():
    """四個來源全失敗時 by_stock 是空的；逐檔不能因此變成「查過沒有」的 []。"""
    got = _events_by_sid(_ev_statuses(failed=list(_events.SOURCE_MARKET)))
    assert got == {"1101": None, "6488": None, "2330": None, "5305": None}


def test_json_events_are_checked_only_for_markets_whose_sources_all_worked():
    hit = _events.Event("1101", "除息", _dt.date(2026, 10, 26), _dt.date(2026, 10, 26), "除息", "TWT48U")

    all_ok = _events_by_sid(_ev_statuses())
    assert all_ok == {"1101": [], "6488": [], "2330": [], "5305": None}   # 市場未知仍是未經檢查

    tpex_down = _events_by_sid(_ev_statuses(failed=[_events.SRC_TPEX_EX]))
    assert tpex_down["6488"] is None and tpex_down["2330"] == []

    twse_down = _events_by_sid(_ev_statuses(failed=[_events.SRC_MOPS_SII]), {"1101": [hit]})
    assert twse_down["2330"] is None and twse_down["6488"] == []
    assert twse_down["1101"][0]["kind"] == "除息"            # 可用來源的命中照列


def test_render_says_event_sources_all_failed_instead_of_no_events():
    statuses = _ev_statuses(failed=list(_events.SOURCE_MARKET))
    md = _live_render([_pool_row("1101")], {"risk": _risk(), "events": _ev({}, statuses)})

    assert "- 事件日曆來源全部不可用（未經檢查，不代表沒有事件" in md
    assert "在可用來源中未見事件" not in md
    assert "見下方「事件日曆」" not in md
    assert ("2. **未來 5 個交易日的事件**：FOMC、美國科技巨頭財報、台廠法說、月營收公布日、除權息"
            "（事件日曆來源全部不可用）") in md


def test_render_keeps_manual_event_items_when_only_unproven_sources_are_up():
    """只剩 MOPS（未證明新鮮）可用時，§5 不能改成「見下方事件日曆」——那等於把未證明的清單當查過。"""
    statuses = [SourceStatus(_events.SRC_MOPS_SII, True, "", proven=False),
                SourceStatus(_events.SRC_MOPS_OTC, True, "", proven=False),
                SourceStatus(_events.SRC_TWT48U, False, "連線失敗"),
                SourceStatus(_events.SRC_TPEX_EX, False, "連線失敗")]
    md = _live_render([_pool_row("1101")], {"risk": _risk(), "events": _ev({}, statuses)})

    assert "見下方「事件日曆」" not in md
    assert ("2. **未來 5 個交易日的事件**：FOMC、美國科技巨頭財報、台廠法說、月營收公布日、除權息"
            "（事件日曆只有未證明新鮮的來源可用）") in md

    # 反向：有一個證明得了新鮮的來源可用時，照常指向事件日曆
    statuses[2] = SourceStatus(_events.SRC_TWT48U, True, "")
    md = _live_render([_pool_row("1101")], {"risk": _risk(), "events": _ev({}, statuses)})
    assert "見下方「事件日曆」" in md


# ---- main()：唯一決定「抓不抓」的地方 ----------------------------------------------------------

class _OutboundBlocked(BaseException):
    """刻意繼承 `BaseException`：生產碼的 `except Exception` 吞不掉。"""


@pytest.fixture
def _main_env(monkeypatch, tmp_path):
    """釘住 DB、日曆與時鐘；即時抓取換成計數 fake。`expected_session` 讀牆鐘，一定要釘。"""
    import socket as _socket

    def guard(self, address):
        raise _OutboundBlocked(f"離線測試嘗試連外 {address}")

    monkeypatch.setattr(_socket.socket, "connect", guard)
    _seed(tmp_path, monkeypatch)
    pool = pd.DataFrame([_pool_row("1101", hi60_prior=80.0), _pool_row("6488", name="環球晶")])
    calls = {"risk": [], "events": []}
    state = {"risk_exc": None}

    monkeypatch.setattr(screen_tw, "get_engine", lambda: object())
    monkeypatch.setattr(screen_tw, "load", lambda eng, date, inc: (
        pd.Timestamp(date) if date else _LIVE_AS_OF, None, None, None, None, None, None, pd.DataFrame()))
    monkeypatch.setattr(screen_tw, "build", lambda *a, **k: (pool.copy(), 0.0))
    monkeypatch.setattr(screen_tw, "funnel", lambda df, mt, strategy: (df, {}))
    monkeypatch.setattr(screen_tw, "data_freshness", lambda *a: None)
    monkeypatch.setattr(screen_tw, "expected_session", lambda: _LIVE_AS_OF.date())
    sessions = {1: _dt.date(2026, 10, 21), 3: _dt.date(2026, 10, 23), 5: _dt.date(2026, 10, 27)}
    monkeypatch.setattr(screen_tw, "sessions_after", lambda day, n: sessions.get(n))
    monkeypatch.setattr(screen_tw, "session_before", lambda day: _dt.date(2026, 10, 19))

    def fake_risk(as_of, nxt):
        calls["risk"].append((as_of, nxt))
        if state["risk_exc"]:
            raise state["risk_exc"]
        return {"6488": RiskHit("注意股", "環球晶", "注意股")}, list(_OK4)

    def fake_upcoming(window):
        calls["events"].append((window.start, window.end, window.prev))
        return {}, [_MOPS_SII_OK]

    monkeypatch.setattr(screen_tw.risk_flags, "fetch_risk_flags", fake_risk)
    monkeypatch.setattr(screen_tw.events, "upcoming", fake_upcoming)

    def run(*argv):
        out, js = tmp_path / "s.md", tmp_path / "s.json"
        assert screen_tw.main(["--out", str(out), "--json", str(js), *argv]) == 0
        import json as _json
        return out.read_text(encoding="utf-8"), _json.loads(js.read_text(encoding="utf-8"))

    return run, calls, state, monkeypatch


def test_main_fetches_live_lists_with_the_next_session(_main_env):
    run, calls, _, _ = _main_env

    md, js = run()

    assert calls["risk"] == [(_dt.date(2026, 10, 20), _dt.date(2026, 10, 21))]
    assert calls["events"] == [(_dt.date(2026, 10, 21), _dt.date(2026, 10, 27), _dt.date(2026, 10, 19))]
    recs = {r["stock_id"]: r for r in js["candidates"]}
    assert recs["6488"]["risk_flag"] == "注意股" and recs["1101"]["risk_flag"] == ""
    assert "### 事件日曆（未來 5 個交易日，10/21~10/27）" in md


def test_main_with_a_date_records_the_reason_and_does_not_fetch(_main_env):
    run, calls, _, _ = _main_env

    md, js = run("--date", "2026-10-20")

    assert calls == {"risk": [], "events": []}
    assert js["risk_flag_skipped"] == screen_tw.SKIP_HISTORICAL
    assert js["event_skipped"] == screen_tw.SKIP_HISTORICAL
    assert f"本報告未附事件日曆：{screen_tw.SKIP_HISTORICAL}" in md
    assert all(r["risk_flag"] is None for r in js["candidates"])


def test_main_skips_when_the_db_is_behind_the_expected_session(_main_env, capsys):
    run, calls, _, mp = _main_env
    mp.setattr(screen_tw, "expected_session", lambda: _dt.date(2026, 10, 21))

    md, js = run()

    assert calls == {"risk": [], "events": []}
    assert "不是預期場次 2026-10-21" in js["risk_flag_skipped"]
    assert "先跑 market_data.cli daily" in js["risk_flag_skipped"]
    assert "**WARN: screen_tw 處置／注意股名單未查" in capsys.readouterr().err


def test_main_skips_without_blaming_the_db_when_it_is_ahead_of_the_expected_session(_main_env, capsys):
    """收盤後手動跑過 daily、還沒到場次完成時點：DB 比預期場次新，叫人重跑 daily 是錯的建議。"""
    run, calls, _, mp = _main_env
    mp.setattr(screen_tw, "expected_session", lambda: _dt.date(2026, 10, 19))

    md, js = run()

    assert calls == {"risk": [], "events": []}
    for reason in (js["risk_flag_skipped"], js["event_skipped"]):
        assert "晚於預期場次 2026-10-19" in reason and "cli daily" not in reason
    assert "cli daily" not in md and "cli daily" not in capsys.readouterr().err


@pytest.mark.parametrize("patch", ["expected_session", "sessions_after"])
def test_main_does_not_fall_back_to_weekdays_without_a_calendar(_main_env, patch):
    run, calls, _, mp = _main_env
    mp.setattr(screen_tw, patch, lambda *a: None)

    _, js = run()

    assert calls == {"risk": [], "events": []}
    assert js["risk_flag_skipped"] == js["event_skipped"] == screen_tw.SKIP_CALENDAR


def test_main_flags_turn_each_feature_off_independently(_main_env):
    run, calls, _, _ = _main_env

    _, js = run("--no-risk-flags")

    assert calls["risk"] == [] and len(calls["events"]) == 1
    assert js["risk_flag_skipped"] == "--no-risk-flags" and js["event_skipped"] is None


def test_main_still_writes_the_report_when_a_fetcher_raises(_main_env, capsys):
    run, calls, state, _ = _main_env
    state["risk_exc"] = RuntimeError("parser bug")

    md, js = run()

    assert "抓取時發生例外（RuntimeError: parser bug）" in js["risk_flag_skipped"]
    assert "名單未取得" in md and "## 3. 候選清單" in md
    assert "**WARN: screen_tw" in capsys.readouterr().err


def test_main_does_not_swallow_the_network_guard(_main_env):
    run, _, state, _ = _main_env
    state["risk_exc"] = _OutboundBlocked("would hit network")
    with pytest.raises(_OutboundBlocked):
        run()


def test_main_passes_event_days_to_the_window(_main_env):
    run, calls, _, _ = _main_env

    md, js = run("--event-days", "3")

    assert calls["events"] == [(_dt.date(2026, 10, 21), _dt.date(2026, 10, 23), _dt.date(2026, 10, 19))]
    assert "### 事件日曆（未來 3 個交易日，10/21~10/23）" in md
    assert js["event_window"] == {"n": 3, "start": "2026-10-21", "end": "2026-10-23"}


def test_main_rejects_a_non_positive_event_window(_main_env):
    run, _, _, _ = _main_env
    with pytest.raises(SystemExit):
        run("--event-days", "0")


# ---- S1：MOPS 未證明新鮮 → 不算查過 ------------------------------------------------------------

def _realistic_ev_statuses(failed=()):
    """實際 `events.upcoming` 的形狀：MOPS 兩源可用但 proven=False，除權息兩源可用且已證明。"""
    out = []
    for name in _events.SOURCE_MARKET:
        unproven = _events.SOURCE_CATEGORY[name] == _events.CAT_CONFERENCE
        out.append(SourceStatus(name, name not in failed, "連線失敗" if name in failed else "",
                                proven=not unproven))
    return out


def _events_json(statuses, by_stock):
    rows = [_pool_row("1101", market="twse"), _pool_row("6488", name="環球晶", market="tpex"),
            _pool_row("2330", name="台積電", market="twse"), _pool_row("5305", name="敦南", market=None)]
    out = screen_tw.to_json(_LIVE_AS_OF, pd.DataFrame(rows), {}, 0.0, "breakout", 5,
                            live={"risk": _risk(), "events": _ev(by_stock, statuses)})
    return {r["stock_id"]: r for r in out["candidates"]}, out


def test_json_unproven_mops_is_never_counted_as_checked():
    """MOPS 回了資料也不能讓沒命中的候選變成 `[]`：凍結的表會漏列新申報。"""
    hit = _events.Event("1101", _events.CONFERENCE, _dt.date(2026, 10, 23), _dt.date(2026, 10, 23),
                        "第三季財務報告", "MOPS", "14:00")
    recs, out = _events_json(_realistic_ev_statuses(), {"1101": [hit]})

    assert recs["2330"]["events"] is None and recs["6488"]["events"] is None   # 不是 []
    assert recs["1101"]["events"][0]["kind"] == "法說"                          # 命中照列
    assert recs["2330"]["events_checked"] == ["除權息"] == recs["6488"]["events_checked"]
    assert recs["5305"]["events_checked"] == []                                 # 市場未知
    proven = {s["name"]: s["proven"] for s in out["event_sources"]}
    assert proven == {_events.SRC_MOPS_SII: False, _events.SRC_MOPS_OTC: False,
                      _events.SRC_TWT48U: True, _events.SRC_TPEX_EX: True}
    assert "法說會（上市 MOPS） 可用但未證明新鮮" in " ".join(out["blind_spots"])


def test_json_events_checked_drops_a_category_whose_source_failed():
    recs, _ = _events_json(_realistic_ev_statuses(failed=[_events.SRC_TPEX_EX]), {})
    assert recs["6488"]["events_checked"] == [] and recs["2330"]["events_checked"] == ["除權息"]


def test_json_events_checked_is_empty_when_events_were_skipped():
    out = screen_tw.to_json(_LIVE_AS_OF, pd.DataFrame([_pool_row("1101", market="twse")]), {}, 0.0,
                            "breakout", 5, live={"risk": _risk(), "events": _skip("--no-events", True)})
    rec = out["candidates"][0]
    assert rec["events"] is None and rec["events_checked"] == []


def test_render_marks_unproven_sources_distinctly():
    md = _live_render([_pool_row("1101")], {"risk": _risk(), "events": _ev({}, _realistic_ev_statuses())})
    assert "- 來源：法說會（上櫃 MOPS） 可用（未證明新鮮）" in md
    assert "- 來源：除權息預告（上櫃 TPEx） 可用" in md
    assert "除權息預告（上櫃 TPEx） 可用（未證明" not in md   # 已證明的來源不能被一起標成未證明


# ---- S3：事件短標進標籤欄與 JSON tags ----------------------------------------------------------

def _tagged_rows(ev):
    pool = pd.DataFrame([_pool_row("1101"), _pool_row("6488", name="環球晶"), _pool_row("3105", name="穩懋")])
    return screen_tw.apply_event_tags(pool, ev)


def _tag_ev():
    d = _dt.date
    return _ev({
        "1101": [_events.Event("1101", "除息", d(2026, 10, 26), d(2026, 10, 26), "", "TWT48U", cash=1.5),
                 _events.Event("1101", _events.CONFERENCE, d(2026, 10, 23), d(2026, 10, 23), "財報", "MOPS"),
                 _events.Event("1101", _events.CONFERENCE, d(2026, 10, 27), d(2026, 10, 27), "財報", "MOPS")],
        "6488": [_events.Event("6488", _events.FORUM, d(2026, 10, 21), d(2026, 10, 22), "受邀", "MOPS")],
    })


def test_event_tags_take_the_earliest_of_each_kind_and_skip_forums():
    pool = _tagged_rows(_tag_ev())
    tags = {r["stock_id"]: tag(r, 0.0) for _, r in pool.iterrows()}

    assert [t for t in tags["1101"] if t.startswith("📅")] == ["📅法說10/23", "📅除息10/26"]
    assert not any(t.startswith("📅") for t in tags["6488"])     # 只有論壇：不上標籤
    assert not any(t.startswith("📅") for t in tags["3105"])


def test_event_tags_flow_into_the_markdown_table_and_json_tags():
    ev = _tag_ev()
    pool = _tagged_rows(ev)
    live = {"risk": _risk(), "events": ev}

    md = screen_tw.render(_LIVE_AS_OF, pool, pool, {}, 0.0, pd.DataFrame(), 25, 2.0, live=live)
    row = next(line for line in md.splitlines() if line.startswith("| 1 | 1101 "))
    assert "| 📅法說10/23 📅除息10/26" in row     # 標籤欄（最後一欄），緊接在處置旗標之後

    out = screen_tw.to_json(_LIVE_AS_OF, pool, {}, 0.0, "breakout", 5, live=live)
    assert "📅除息10/26" in out["candidates"][0]["tags"]


def test_event_tags_are_absent_when_events_were_skipped():
    pool = _tagged_rows(_skip("--no-events", True))
    assert "event_tags" not in pool.columns
    assert not any(t.startswith("📅") for t in tag(pool.iloc[0], 0.0))


# ---- S11：使用者自己關掉時不逐檔列「未經檢查」 -------------------------------------------------

@pytest.mark.parametrize("argv", [["--no-risk-flags"], ["--date", "2026-10-20"]])
def test_main_opted_out_prints_only_the_status_line(_main_env, argv):
    run, _, _, _ = _main_env
    md, js = run(*argv)
    assert "- 處置／注意股名單：未查（" in md
    assert "名單未取得" not in md and "以下候選未經檢查" not in md
    assert all(r["risk_flag"] is None for r in js["candidates"])


def test_main_stale_db_still_lists_unchecked_candidates(_main_env):
    run, _, _, mp = _main_env
    mp.setattr(screen_tw, "expected_session", lambda: _dt.date(2026, 10, 21))
    md, _ = run()
    assert "### ⚠ 處置／注意股名單未取得：基準日 2026-10-20 不是預期場次" in md
