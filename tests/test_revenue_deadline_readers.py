"""回測與歷史回放讀取端都要套共用的月營收法定期限（market_data.revenue_deadline）。

DB 的 announce_date 是佔位「次月 10 日」：2020-01 營收展延到 2/15、2026 起保險類
（保守口徑 28xx 加 5880、2207、2905）期限是 15 日，期限遇休市日順延到下一個交易日；
讀取端沒套就會在法定期限前「看到」還沒公布的營收。
每個讀取端各自的可見日語意不變，所以斷言寫成「該讀取端第一個看得到的交易日」：
- msf.pit_revenue_panel：公告日之後第一個交易日（嚴格 <）。
- backtest_screen._pit：forward 到交易日（含當日）再 shift(1)。
- screen_tw.load（--date 回放）：公告日嚴格小於基準日、且在 45 曆日保鮮期內。
- tw_stock_dossier.fundamentals（pit=True）：公告日小於等於基準日。
2020-02-15 是週六（順延到 02-17 週一，當晚申報者 02-18 才看得到）、2026-04-15 是週三、
2026-04-10 是週五。
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import backtest_screen as bs  # noqa: E402
import measure_signal_forward as msf  # noqa: E402
import screen_tw  # noqa: E402
from measure_revenue_momentum import (  # noqa: E402
    candidate_yoy_frame,
    correct_pit_dates,
    effective_announce,
)

SIDS = ["2881", "2330"]
DAYS = pd.bdate_range("2020-01-02", "2020-03-31").append(pd.bdate_range("2026-03-02", "2026-05-29"))

# DB 現況：彙總報表寫入的佔位公告日一律是次月 10 日
REV = pd.DataFrame({
    "stock_id": ["2881", "2330", "2881", "2330"],
    "revenue_month": pd.to_datetime(["2026-03-01", "2026-03-01", "2020-01-01", "2020-01-01"]),
    "date": pd.to_datetime(["2026-04-10", "2026-04-10", "2020-02-10", "2020-02-10"]),
    "yoy": [50.0, 30.0, 20.0, 25.0],
})


def _fake_read_sql(sql, con, params=None, parse_dates=None):
    q = str(sql)
    if "market.monthly_revenue" in q:
        cols = ["stock_id", "date", "yoy"] + (["revenue_month"] if "revenue_month" in q else [])
        return REV[cols].copy()
    if "market.price" in q:
        rows = [{"stock_id": s, "date": d, "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0,
                 "volume": 1000.0, "turnover": 1e9, "pe_ratio": 10.0} for d in DAYS for s in SIDS]
        return pd.DataFrame(rows)
    if "market.institutional" in q:
        return pd.DataFrame([{"stock_id": s, "date": d, "foreign_net": 0, "trust_net": 0,
                              "dealer_net": 0} for d in DAYS for s in SIDS])
    if "market.valuation" in q:
        return pd.DataFrame(columns=["stock_id", "date", "pb_ratio", "dividend_yield"])
    if "market.stock_info" in q:
        return pd.DataFrame({"stock_id": SIDS, "industry": ["金融", "半導體"], "name": ["富邦金", "台積電"]})
    raise AssertionError(q)


class _Engine:
    @contextmanager
    def connect(self):
        yield None


@pytest.fixture
def fake_db(monkeypatch):
    monkeypatch.setattr(pd, "read_sql", _fake_read_sql)
    half = lambda engine, idx, cols: pd.DataFrame(0.5, index=idx, columns=cols)  # noqa: E731
    monkeypatch.setattr(bs, "load_factors", half)
    monkeypatch.setattr(msf, "load_factors", half)


def _first_visible(panel, sid, after):
    s = panel[sid]
    s = s[(s.index > pd.Timestamp(after)) & s.notna()]
    return s.index[0].strftime("%Y-%m-%d")


def _assert_visibility(panel, *, fin_2026, gen_2026, gen_2020):
    assert _first_visible(panel, "2881", "2026-03-31") == fin_2026
    assert _first_visible(panel, "2330", "2026-03-31") == gen_2026
    assert _first_visible(panel, "2330", "2020-01-31") == gen_2020
    assert _first_visible(panel, "2881", "2020-01-31") == gen_2020


def test_measure_signal_forward_load_applies_deadline(fake_db):
    piv, rv, _ = msf.load(_Engine(), "2020-02-01", "2026-05-29", include_otc_revenue=True)
    panel = msf.pit_revenue_panel(rv, piv["close"].index, piv["close"].columns)
    assert pd.isna(panel.at[pd.Timestamp("2026-04-13"), "2881"])   # 富邦金 04-13 還看不到
    _assert_visibility(panel, fin_2026="2026-04-16", gen_2026="2026-04-13", gen_2020="2020-02-18")


def test_backtest_screen_load_applies_deadline(fake_db):
    piv, inst, val, rev = bs.load_panel(_Engine(), "2020-02-01", "2026-05-29", include_otc_revenue=True)
    ind = bs.build_indicators(piv["close"], piv["turnover"], inst, piv["pe_ratio"],
                              piv["high"], piv["low"], lag_days=1, val=val, rev=rev)
    panel = ind["rev_yoy"]
    assert pd.isna(panel.at[pd.Timestamp("2026-04-13"), "2881"])
    _assert_visibility(panel, fin_2026="2026-04-16", gen_2026="2026-04-13", gen_2020="2020-02-18")


def test_measure_revenue_momentum_readers_apply_deadline():
    idx, cols = DAYS, pd.Index(SIDS)
    # effective_announce（revenue_features 形狀，有 revenue_month）
    rv = REV.rename(columns={"date": "announce_date"})
    panel = msf.pit_revenue_panel(candidate_yoy_frame(effective_announce(rv)), idx, cols)
    _assert_visibility(panel, fin_2026="2026-04-16", gen_2026="2026-04-13", gen_2020="2020-02-18")
    # correct_pit_dates（measure_market_regime 走的路）：有無 revenue_month 欄都要對
    for frame in (REV, REV.drop(columns=["revenue_month"])):
        panel = msf.pit_revenue_panel(correct_pit_dates(frame), idx, cols)
        _assert_visibility(panel, fin_2026="2026-04-16", gen_2026="2026-04-13", gen_2020="2020-02-18")


# ---- 歷史回放讀取端：screen_tw --date、tw_stock_dossier 帶 as_of -------------------------

@pytest.mark.parametrize("as_of, latest, replay", [
    (None, "2026-04-13", False),
    ("2026-04-12", "2026-04-13", True),
    ("2026-04-13", "2026-04-13", False),
    ("2026-04-14", "2026-04-13", False),
    (pd.Timestamp("2026-04-13").date(), pd.Timestamp("2026-04-13"), False),
    (pd.Timestamp("2026-04-12"), pd.Timestamp("2026-04-13").date(), True),
    ("2026-04-13 00:00:00", "2026-04-13 13:30:00", False),
    ("2026-04-12", None, False),
    (pd.NaT, "2026-04-13", False),
    ("2026-04-12", pd.NaT, False),
])
def test_replay_requires_an_explicit_date_before_latest(as_of, latest, replay):
    from market_data.revenue_deadline import is_historical_replay

    assert is_historical_replay(as_of, latest) is replay


class _ScreenConn:
    def __init__(self, latest):
        self.latest = latest

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *a, **k):
        latest = self.latest

        class _R:
            def scalar(self):
                return latest
        return _R()


class _ScreenEngine:
    def __init__(self, latest):
        self.latest = latest

    def connect(self):
        return _ScreenConn(self.latest)


def _screen_rev(monkeypatch, as_of, latest="2026-05-29"):
    """screen_tw.load 讀到的月營收列；假 read_sql 照 SQL 的公告日參數篩（驗 SQL 窗口有放寬）。"""
    seen = {}

    def fake(sql, con, params=None, parse_dates=None):
        q = str(sql)
        if "market.monthly_revenue" in q:
            seen.update(params)
            ann = REV["date"]
            rows = REV[(ann >= pd.Timestamp(params["s"])) & (ann < pd.Timestamp(params["e"]))]
            return rows.rename(columns={"date": "announce_date"}).assign(mom=0.0).reset_index(drop=True)
        if "market.price" in q:
            return pd.DataFrame([{"stock_id": s, "date": d, "open": 10.0, "high": 10.0, "low": 10.0,
                                  "close": 10.0, "volume": 1.0, "turnover": 1.0} for d in DAYS for s in SIDS])
        if "market.market_index" in q:
            return pd.DataFrame(columns=["date", "close", "change"])
        return pd.DataFrame(columns=["stock_id", "date"])

    monkeypatch.setattr(pd, "read_sql", fake)
    monkeypatch.setattr(screen_tw, "load_factors", lambda eng, idx, cols: pd.DataFrame(1.0, index=idx, columns=cols))
    rev = screen_tw.load(_ScreenEngine(pd.Timestamp(latest)), as_of, include_otc_revenue=True)[5]
    return sorted(rev["stock_id"]), seen


@pytest.mark.parametrize("as_of, visible", [
    ("2026-04-13", ["2330"]),            # 富邦金期限 04-15：回放 04-13 還看不到
    ("2026-04-15", ["2330"]),            # 嚴格小於：期限當天仍看不到（當晚才申報）
    ("2026-04-16", ["2330", "2881"]),
    ("2026-05-25", ["2330", "2881"]),    # 保鮮期 45 天：2330（04-10）到 05-25 為止
    ("2026-05-26", ["2881"]),            # 05-26 起 2330 過期，富邦金以有效公告日 04-15 計還在
    ("2026-05-30", ["2881"]),
    ("2026-05-31", []),
])
def test_screen_tw_replay_applies_deadline(monkeypatch, as_of, visible):
    assert _screen_rev(monkeypatch, pd.Timestamp(as_of), latest="2026-06-01")[0] == visible


@pytest.mark.parametrize("as_of", [None, "2026-04-13", "2026-04-14"])
def test_screen_tw_live_keeps_placeholder(monkeypatch, as_of):
    # 不帶日期、等於或晚於最新場次都屬 live，不能把已公布的富邦金營收藏到 04-15 之後
    sids, seen = _screen_rev(monkeypatch, as_of, latest="2026-04-13")
    assert sids == ["2330", "2881"]
    assert pd.Timestamp(seen["s"]) == pd.Timestamp(as_of or "2026-04-13") - pd.Timedelta(days=45)


def _dossier_revenue(monkeypatch):
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()
    from src.services import tw_stock_dossier as dossier

    months = pd.period_range("2024-03", "2026-03", freq="M").to_timestamp()[::-1]
    rev = pd.DataFrame({"revenue_month": months, "revenue": 100, "yoy": None,
                        "announce_date": [(m + pd.DateOffset(months=1, days=9)).date() for m in months]})

    def fake_sql(engine, sql, **kw):
        if "market.price" in sql:
            days = pd.to_datetime(["2026-04-10", "2026-04-13"])
            if kw.get("a") is not None:
                days = days[days <= pd.Timestamp(kw["a"])]
            return pd.DataFrame({"d": [days.max()]})
        if "monthly_revenue" in sql:
            return rev[rev["announce_date"] <= pd.Timestamp(kw["d"]).date()].reset_index(drop=True)
        return pd.DataFrame(columns=["date", "account", "value"])

    monkeypatch.setattr(dossier, "_sql", fake_sql)
    return dossier


def _dossier_months(monkeypatch, sid, as_of, pit):
    dossier = _dossier_revenue(monkeypatch)
    out = dossier.fundamentals(None, sid, as_of, pit=pit)["monthly_revenue"]
    return out[-1]["month"]


@pytest.mark.parametrize("sid, as_of, pit, latest", [
    ("2881", "2026-04-13", True, "2026-02"),    # 回放：富邦金 2026-03 營收 04-15 才到期，看不到
    ("2905", "2026-04-13", True, "2026-02"),    # 三商投控同為保險類
    ("2881", "2026-04-15", True, "2026-03"),    # 期限當天（小於等於）看得到
    ("2330", "2026-04-13", True, "2026-03"),    # 反向：一般公司 10 日
    ("2881", "2026-04-13", False, "2026-03"),   # 反向：live 不套期限
])
def test_dossier_fundamentals_pit_applies_deadline(monkeypatch, sid, as_of, pit, latest):
    assert _dossier_months(monkeypatch, sid, as_of, pit) == latest


@pytest.mark.parametrize("as_of, latest, month, price_date", [
    (None, "2026-04-14", "2026-03", "2026-04-13"),
    ("2026-04-13", "2026-04-13", "2026-03", "2026-04-13"),
    ("2026-04-14", "2026-04-13", "2026-03", "2026-04-13"),
    ("2026-04-13", "2026-04-14", "2026-02", "2026-04-13"),
    ("2026-04-12", "2026-04-13", "2026-02", "2026-04-10"),
    ("2026-04-14", "2026-04-14", "2026-03", "2026-04-13"),
])
def test_dossier_build_replays_only_before_latest_market_date(monkeypatch, as_of, latest, month, price_date):
    dossier = _dossier_revenue(monkeypatch)
    monkeypatch.setattr(dossier, "_check_suffix", lambda code: None)
    monkeypatch.setattr(dossier.market_repo, "latest_price_date", lambda engine: pd.Timestamp(latest).date())
    monkeypatch.setattr(dossier, "technicals", lambda *a, **k: (None, []))
    monkeypatch.setattr(dossier, "stock_name", lambda sid, engine=None: None)
    monkeypatch.setattr(dossier, "contract_liabilities", lambda *a: [])
    monkeypatch.setattr(dossier, "chips", lambda *a, **k: {})
    monkeypatch.setattr(dossier, "valuation", lambda *a: None)
    out = dossier.build("2881.TW", as_of=as_of, engine=object())
    assert out["errors"] == []
    assert out["as_of"] == price_date
    assert out["fundamentals"]["monthly_revenue"][-1]["month"] == month


def _dossier_limited(monkeypatch, sid, as_of, pit):
    """假 _sql 照 SQL 的 LIMIT 截列（先套公告日篩選再截），才量得到列數上限夠不夠 pit 篩掉最新月份後用。"""
    import re

    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()
    from src.services import tw_stock_dossier as dossier

    months = pd.period_range("2023-01", "2026-03", freq="M").to_timestamp()[::-1]
    # 營收逐月遞增、庫存 yoy 留空：表格最舊一列的 yoy 只能靠去年同月營收自己算，退回值是 None
    rev = pd.DataFrame({"revenue_month": months,
                        "revenue": [1000 + i for i in range(len(months))][::-1],
                        "yoy": None,
                        "announce_date": [(m + pd.DateOffset(months=1, days=9)).date() for m in months]})

    def fake_sql(engine, sql, **kw):
        if "monthly_revenue" in sql:
            limit = int(re.search(r"LIMIT (\d+)", sql).group(1))
            return rev[rev["announce_date"] <= pd.Timestamp(kw["d"]).date()].head(limit).reset_index(drop=True)
        return pd.DataFrame(columns=["date", "account", "value"])

    monkeypatch.setattr(dossier, "_sql", fake_sql)
    return dossier.fundamentals(None, sid, as_of, pit=pit)


@pytest.mark.parametrize("sid, as_of, pit, latest", [
    ("2881", "2026-04-13", True, "2026-02"),    # 回放：保險類最新月份被 pit 篩掉，仍要湊滿表格與 TTM
    ("2881", "2026-04-13", False, "2026-03"),   # 反向：live 不篩，同一份資料照樣完整
    ("2330", "2026-04-13", True, "2026-03"),    # 反向：一般公司 pit 不篩
])
def test_dossier_row_cap_survives_pit_drop(monkeypatch, sid, as_of, pit, latest):
    out = _dossier_limited(monkeypatch, sid, as_of, pit)
    table = out["monthly_revenue"]
    assert len(table) == 13 and table[-1]["month"] == latest
    # 13 列都要有自己算的年增率（最舊一列靠第 25 列的去年同月），TTM 要有連續 24 個月
    assert all(m["yoy_pct"] is not None for m in table)
    assert out["ttm_revenue_yoy_pct"] is not None
