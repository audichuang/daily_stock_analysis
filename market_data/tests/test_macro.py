"""market_data.macro：解析純函式（不連外）＋入庫語意（pg_conn，種 1900／2099 年資料）。"""

import datetime
import math

import pandas as pd
import pytest
from sqlalchemy import text

from market_data import macro

D = datetime.date
NOW = datetime.datetime(2099, 1, 1, tzinfo=datetime.timezone.utc)


# ---------- 清單 ----------

def test_overnight_list_comes_from_the_single_series_list():
    ids = [t for _, t, _, _ in macro.overnight_series()]
    assert ids[:6] == ["^DJI", "^GSPC", "^IXIC", "^SOX", "TSM", "MU"]
    assert "^TNX" not in ids, "總經序列不能混進 overnight 的表（會打亂它的分組與日期檢查）"
    assert {"^TNX", "DX-Y.NYB", "GC=F", "BZ=F", "HYG", "EWT", "FRED:DGS2"} <= {s.id for s in macro.SERIES}
    assert len({s.id for s in macro.SERIES}) == len(macro.SERIES)


def test_persist_enabled_defaults_on(monkeypatch):
    monkeypatch.delenv(macro.FLAG_ENV, raising=False)
    assert macro.persist_enabled()
    for off in ("0", "false", "OFF", " no "):
        monkeypatch.setenv(macro.FLAG_ENV, off)
        assert not macro.persist_enabled()
    monkeypatch.setenv(macro.FLAG_ENV, "true")
    assert macro.persist_enabled()


def test_watchlist_env_overrides_default(monkeypatch):
    monkeypatch.delenv(macro.WATCHLIST_ENV, raising=False)
    assert macro.watchlist() == list(macro.DEFAULT_WATCHLIST)
    monkeypatch.setenv(macro.WATCHLIST_ENV, " nvda, ,tsm ")
    assert macro.watchlist() == ["NVDA", "TSM"]


# ---------- macro_series ----------

def test_yf_rows_use_each_rows_own_date_and_skip_nan():
    idx = pd.DatetimeIndex(["2099-01-02", "2099-01-05", "2099-01-06"]).tz_localize("America/New_York")
    rows = macro.yf_rows("^TNX", pd.Series([4.5, math.nan, 4.6], index=idx), now=NOW)
    assert [(r["date"], r["value"]) for r in rows] == [(D(2099, 1, 2), 4.5), (D(2099, 1, 6), 4.6)]
    assert {r["source"] for r in rows} == {"yfinance"}


def test_parse_fred_csv_skips_missing_and_rejects_wrong_header():
    rows = macro.parse_fred_csv("FRED:DGS2", "observation_date,DGS2\n2099-01-02,4.65\n2099-01-03,.\n2099-01-06,\n",
                                now=NOW)
    assert [(r["date"], r["value"]) for r in rows] == [(D(2099, 1, 2), 4.65)]
    with pytest.raises(ValueError):
        macro.parse_fred_csv("FRED:DGS2", "observation_date,DGS10\n2099-01-02,4.9\n")


# ---------- rate_expectations ----------

def test_prob_mid_uses_bid_ask_not_last_price():
    payload = {"markets": [{
        "ticker": "KXFEDDECISION-27MAR-C25", "close_time": "2027-03-17T17:59:00Z",
        "yes_bid_dollars": "0.0600", "yes_ask_dollars": "0.1300", "last_price_dollars": "0.3500",
        "volume_fp": "1200.00", "open_interest_fp": "800.00", "updated_time": "2026-10-26T10:00:00Z"}]}
    (row,) = macro.parse_kalshi(payload, D(2026, 10, 26))
    assert row["prob_mid"] == pytest.approx(0.095), "陳舊的 last_price 0.35 不能當機率"
    assert row["last_price"] == pytest.approx(0.35)
    assert row["outcome"] == "cut_25"
    assert row["meeting_date"] == D(2027, 3, 17)
    assert row["source_updated_at"].tzinfo is not None


def test_prob_mid_is_none_without_an_ask():
    assert macro.prob_mid(0.01, 0.0) is None
    assert macro.prob_mid(None, 0.05) is None
    assert macro.prob_mid(0.0, 0.01) == pytest.approx(0.005)


def test_meeting_date_is_the_new_york_date():
    # 02:00 UTC 在美東還是前一天
    assert macro.meeting_date_of("2027-01-27T02:00:00Z") == D(2027, 1, 26)
    assert macro.meeting_date_of("2026-10-28T17:59:00Z") == D(2026, 10, 28)


def test_unknown_outcome_suffix_is_skipped():
    payload = {"markets": [
        {"ticker": "KXFEDDECISION-26OCT-H50", "close_time": "2026-10-28T17:59:00Z"},
        {"ticker": "KXFEDDECISION-26OCT-H0", "close_time": "2026-10-28T17:59:00Z",
         "yes_bid_dollars": "0.94", "yes_ask_dollars": "0.95"}]}
    rows = macro.parse_kalshi(payload, D(2026, 10, 26))
    assert [r["outcome"] for r in rows] == ["hold"]


# ---------- event_calendar ----------

FED_HTML = """
<h4><a id="1">2026 FOMC Meetings</a></h4>
<div class="fomc-meeting__month col"><strong>January</strong></div>
<div class="fomc-meeting__date col">27-28</div>
<div class="fomc-meeting__month col"><strong>April/May</strong></div>
<div class="fomc-meeting__date col">30-1</div>
<div class="fomc-meeting__month col"><strong>September</strong></div>
<div class="fomc-meeting__date col">15-16*</div>
<div class="fomc-meeting__month col"><strong>October</strong></div>
<div class="fomc-meeting__date col">5 (unscheduled)</div>
<h4><a id="2">2025 FOMC Meetings</a></h4>
<div class="fomc-meeting__month col"><strong>Dec</strong></div>
<div class="fomc-meeting__date col">9-10</div>
"""


def test_parse_fed_calendar_takes_last_day_and_skips_unscheduled():
    assert macro.parse_fed_calendar(FED_HTML) == [
        D(2025, 12, 10), D(2026, 1, 28), D(2026, 5, 1), D(2026, 9, 16)]


def test_fomc_events_prefer_fed_and_mark_kalshi_only_as_estimated():
    events = macro.fomc_events([D(2026, 10, 28), D(2026, 12, 9)],
                               [D(2026, 10, 28), D(2026, 12, 10), D(2027, 1, 27)], now=NOW)
    by = {e["label"]: e for e in events}
    assert by["2026-10"]["source"] == "fed+kalshi" and by["2026-10"]["status"] == "confirmed"
    assert by["2026-12"]["event_date"] == D(2026, 12, 9), "兩邊不一致以官網為準"
    assert by["2026-12"]["source"].startswith("fed(")
    assert by["2027-01"]["status"] == "estimated" and by["2027-01"]["source"] == "kalshi"


def test_earnings_event_is_estimated_and_keyed_by_quarter():
    ev = macro.earnings_event("MSFT", {"Earnings Date": [D(2026, 10, 29), D(2026, 11, 2)],
                                       "Earnings Average": 4.71992}, now=NOW)
    assert ev["event_date"] == D(2026, 10, 29) and ev["label"] == "2026Q4"
    assert ev["status"] == "estimated" and ev["time_note"] == "區間"
    assert "4.72" in ev["title"]
    assert macro.earnings_event("X", {}) is None
    assert macro.earnings_event("X", None) is None


# ---------- 入庫（pg_conn） ----------

def _event(symbol, label, date, etype="earnings"):
    return {"event_type": etype, "symbol": symbol, "label": label, "event_date": date, "status": "estimated",
            "title": f"{symbol} test", "time_note": None, "source": "test", "updated_at": NOW}


def test_store_events_moves_a_rescheduled_date_instead_of_duplicating(pg_conn):
    today = D(2099, 1, 1)
    macro.store_events(pg_conn, [_event("ZZTEST", "2099Q1", D(2099, 3, 30)),
                                 _event("ZZOTHER", "2099Q1", D(2099, 2, 1))], today)
    # 改期但仍在同一季：同鍵更新
    macro.store_events(pg_conn, [_event("ZZTEST", "2099Q1", D(2099, 3, 31))], today)
    # 改期跨季：舊季那筆（未來日期）要被刪掉，別的 symbol 不受影響
    macro.store_events(pg_conn, [_event("ZZTEST", "2099Q2", D(2099, 4, 2))], today)
    rows = pg_conn.execute(text(
        "SELECT symbol, label, event_date FROM market.event_calendar WHERE symbol LIKE 'ZZ%' ORDER BY 1, 2")).all()
    assert [tuple(r) for r in rows] == [("ZZOTHER", "2099Q1", D(2099, 2, 1)), ("ZZTEST", "2099Q2", D(2099, 4, 2))]


def test_store_events_keeps_past_events(pg_conn):
    macro.store_events(pg_conn, [_event("ZZPAST", "1900Q1", D(1900, 1, 5))], D(1900, 1, 1))
    macro.store_events(pg_conn, [_event("ZZPAST", "1900Q2", D(1900, 4, 5))], D(1900, 3, 1))
    labels = pg_conn.execute(text(
        "SELECT label FROM market.event_calendar WHERE symbol = 'ZZPAST' ORDER BY 1")).scalars().all()
    assert labels == ["1900Q1", "1900Q2"], "已經過去的事件是歷史，不能因為這次沒抓到就刪"


def test_fomc_fallback_keeps_confirmed_meetings(pg_conn):
    """官網掛掉時只剩 Kalshi：不能刪掉 Kalshi 視野外的已確認會議，也不能用 estimated 蓋掉 confirmed。"""
    today = D(2099, 1, 1)
    fed = [{**_event("ZZFED", "2099-01", D(2099, 1, 28), etype="fomc"), "status": "confirmed"},
           {**_event("ZZFED", "2099-03", D(2099, 3, 18), etype="fomc"), "status": "confirmed"}]
    macro.store_events(pg_conn, fed, today)
    kalshi_only = [_event("ZZFED", "2099-01", D(2099, 1, 29), etype="fomc"),
                   _event("ZZFED", "2099-05", D(2099, 5, 6), etype="fomc")]
    macro.store_events(pg_conn, kalshi_only, today)
    rows = pg_conn.execute(text(
        "SELECT label, event_date, status FROM market.event_calendar WHERE symbol = 'ZZFED' ORDER BY 1")).all()
    assert [tuple(r) for r in rows] == [("2099-01", D(2099, 1, 28), "confirmed"),
                                        ("2099-03", D(2099, 3, 18), "confirmed"),
                                        ("2099-05", D(2099, 5, 6), "estimated")]
    # 官網恢復後，confirmed 照常覆蓋
    macro.store_events(pg_conn, [{**_event("ZZFED", "2099-05", D(2099, 5, 5), etype="fomc"),
                                  "status": "confirmed"}], today)
    assert pg_conn.execute(text(
        "SELECT event_date FROM market.event_calendar WHERE symbol = 'ZZFED' AND label = '2099-05'")).scalar() \
        == D(2099, 5, 5)
    # 官網自己改期（confirmed 蓋 confirmed）也要生效
    macro.store_events(pg_conn, [{**_event("ZZFED", "2099-01", D(2099, 1, 27), etype="fomc"),
                                  "status": "confirmed"}], today)
    assert pg_conn.execute(text(
        "SELECT event_date FROM market.event_calendar WHERE symbol = 'ZZFED' AND label = '2099-01'")).scalar() \
        == D(2099, 1, 27)


def test_fetch_series_stores_unadjusted_closes(monkeypatch):
    """還原價會在除息後改寫整段歷史，而每天只重抓 3 個月；一定要抓未還原收盤。"""
    import sys
    import types

    seen = []

    class _Ticker:
        def __init__(self, sid): self.sid = sid

        def history(self, period, auto_adjust=True):
            seen.append(auto_adjust)
            idx = pd.DatetimeIndex(["2099-01-02"])
            return pd.DataFrame({"Close": [1.0]}, index=idx)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_Ticker))
    monkeypatch.setattr(macro, "SERIES", (macro.Series("ZZ", "zz", "macro", "index", False, ""),))
    rows, failed = macro.fetch_series(today=D(2099, 1, 3), out=lambda *_: None)
    assert seen == [False] and failed == [] and rows[0]["date"] == D(2099, 1, 2)


def test_store_series_and_rates_are_idempotent_upserts(pg_conn):
    rows = [{"series_id": "ZZ:TEST", "date": D(1900, 1, 2), "value": 1.0, "source": "test", "updated_at": NOW}]
    macro.store_series(pg_conn, rows)
    macro.store_series(pg_conn, [{**rows[0], "value": 2.0}])
    assert pg_conn.execute(text(
        "SELECT value::float FROM market.macro_series WHERE series_id = 'ZZ:TEST'")).scalars().all() == [2.0]
    rate = {"snapshot_date": D(1900, 1, 2), "meeting_date": D(1900, 1, 30), "outcome": "hold", "prob_mid": 0.5,
            "yes_bid": 0.49, "yes_ask": 0.51, "last_price": None, "volume": None, "open_interest": None,
            "source_updated_at": None, "source": "test"}
    macro.store_rates(pg_conn, [rate])
    macro.store_rates(pg_conn, [{**rate, "prob_mid": 0.6}])
    assert pg_conn.execute(text(
        "SELECT prob_mid::float FROM market.rate_expectations WHERE snapshot_date = '1900-01-02'")).scalars().all() == [0.6]


def test_update_sections_fail_independently(monkeypatch, capsys):
    """Kalshi 掛掉不能讓 macro_series 與 event_calendar 跟著不寫。"""
    stored = []
    monkeypatch.setattr(macro, "fetch_series", lambda **k: ([{"date": D(2099, 1, 2)}], []))
    monkeypatch.setattr(macro, "store_series", lambda conn, rows: stored.append("series") or len(rows))
    monkeypatch.setattr(macro, "store_events", lambda conn, rows, today: stored.append("events") or len(rows))
    monkeypatch.setattr(macro, "watchlist", lambda: [])

    def fake_get(url, **k):
        raise ConnectionError(f"down {url[:30]}")

    monkeypatch.setattr(macro, "http_get", fake_get)

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Eng:
        def begin(self): return _Conn()

    result = macro.update(_Eng())
    out = capsys.readouterr().out
    assert stored == ["series", "events"]
    assert result["macro_series"] == 1 and result["rate_expectations"] == 0
    assert "**WARN rate_expectations" in out and "**WARN event_calendar fomc" in out
