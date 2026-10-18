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
        {**base, "stock_id": "AAA", "vol_ratio5": 1.5},   # 在區間內
        {**base, "stock_id": "BBB", "vol_ratio5": 5.0},   # 爆量,應被剔除
        {**base, "stock_id": "CCC", "vol_ratio5": 1.0},   # 量能不足,應被剔除
    ])
    pool, steps = funnel(df, 2e8, "breakout")
    assert list(pool["stock_id"]) == ["AAA"]
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
        {**base, "stock_id": "AAA", "yoy": 25.0},
        {**base, "stock_id": "BBB", "yoy": 5.0},
        {**base, "stock_id": "CCC", "yoy": float("nan")},   # 上櫃無月營收 → 篩掉
    ])
    pool, _ = funnel(df, 2e8, "breakout")
    assert list(pool["stock_id"]) == ["AAA"]


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
# 法人／融資／估值只收上市；18:00 時法人與融資常停在前一天。這些都是「數字看起來完整其實不是」
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
