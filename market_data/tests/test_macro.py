"""market_data.macro：解析純函式（不連外）＋入庫語意（pg_conn，種 1900／2099 年資料）。"""

import datetime
import math
import pathlib
import types

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


def test_daily_refetches_the_whole_window_the_brief_reads():
    """Yahoo 的 Close 已做分割調整；只重抓近期的話，分割後新舊列尺度不同（假的 −50% 回撤）。
    每日窗口必須涵蓋儀表讀的一年高點與 MA200（約 260 個交易日）。"""
    years = {"1y": 1, "2y": 2, "5y": 5, "10y": 10, "max": 99}
    assert years.get(macro.YF_PERIOD, 0) >= 2
    assert macro.FRED_LOOKBACK_DAYS >= 400


# ---------- 經濟數據：ALFRED 首發值、FRED／BEA／Census 行事曆、ISM、央行 ----------

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _fx(name):
    return (FIXTURES / name).read_bytes().decode("utf-8")


def test_series_freq_has_a_default_and_icsa_is_weekly():
    assert macro.Series("ZZ", "zz", "macro", "index", False, "").freq == "daily"
    by = {s.id: s for s in macro.SERIES}
    assert by["FRED:ICSA"].freq == "weekly" and by["FRED:ICSA"].overnight is False
    assert not {"FRED:PAYEMS", "FRED:UNRATE"} & set(by), "月頻、會修訂的序列不進日線表"
    assert all(s.freq == "daily" for s in macro.SERIES if s.id != "FRED:ICSA")


def test_parse_alfred_csv_reads_the_vintage_from_the_header():
    vintage, points = macro.parse_alfred_csv("ICSA", _fx("macro_alfred_icsa_20261010.bin"))
    assert vintage == D(2026, 10, 10)
    assert points[-1] == (D(2026, 10, 3), 197000.0), "首發 vintage 的值，不是現值 198000"
    vintage, points = macro.parse_alfred_csv("PAYEMS", _fx("macro_alfred_payems_20260905.bin"))
    assert vintage == D(2026, 9, 5) and points[-1] == (D(2026, 8, 1), 159075.0)


def test_parse_alfred_csv_rejects_headers_without_a_vintage_suffix():
    # 參數被靜默忽略時，ALFRED 回的是最新值、表頭沒有後綴：不能當首發值收
    with pytest.raises(ValueError):
        macro.parse_alfred_csv("ICSA", "observation_date,ICSA\n2026-10-03,198000\n")
    with pytest.raises(ValueError):
        macro.parse_alfred_csv("ICSA", "observation_date,PAYEMS_20261010\n2026-10-03,1\n")


def _alfred(code, vintage, rows):
    body = "".join(f"{d},{v}\n" for d, v in rows)
    return f"observation_date,{code}_{vintage:%Y%m%d}\n{body}"


def test_fetch_first_release_uses_vintage_param_and_returns_prior_in_same_vintage(monkeypatch):
    urls = []

    def fake_get(url, **k):
        urls.append(url)
        if "vintage_date=2026-11-06" in url:
            text_ = _alfred("PAYEMS", D(2026, 11, 6), [("2026-08-01", 159015), ("2026-09-01", 159200),
                                                      ("2026-10-01", 159350)])
        else:
            text_ = _alfred("PAYEMS", D(2026, 11, 5), [("2026-08-01", 159015), ("2026-09-01", 159180)])
        return types.SimpleNamespace(text=text_)

    monkeypatch.setattr(macro, "http_get", fake_get)
    got = macro.fetch_first_release("PAYEMS", D(2026, 11, 6))
    assert got == {"obs_date": D(2026, 10, 1), "actual": 159350.0, "prior": 159200.0, "vintage": D(2026, 11, 6)}
    assert all("vintage_date=" in u and "vintage_dates" not in u for u in urls)


def test_fetch_first_release_returns_none_until_alfred_has_the_new_observation(monkeypatch):
    # 公布日的 vintage 最後一筆沒有比前一天新＝ALFRED 還沒收進來；現在寫會把舊月份的值當首發值
    monkeypatch.setattr(macro, "http_get", lambda url, **k: types.SimpleNamespace(
        text=_alfred("PAYEMS", D(2026, 11, 6), [("2026-09-01", 159200)])))
    assert macro.fetch_first_release("PAYEMS", D(2026, 11, 6)) is None


def test_fred_calendar_is_central_time_cpi_0730_ct_is_1330z():
    times = macro.parse_fred_release_calendar(_fx("macro_fred_calendar_cpi_2026.bin"))
    assert len(times) == 12
    oct14 = next(t for t in times if t.astimezone(macro.NEW_YORK).date() == D(2026, 10, 14))
    assert oct14.astimezone(macro.UTC) == datetime.datetime(2026, 10, 14, 12, 30, tzinfo=macro.UTC)  # EDT：08:30 ET
    # 冬令（CST，UTC−6）：7:30 CT ＝ 13:30Z，與 BEA 對過的 PCE 11-25 同一個結構
    winter = macro.parse_fred_release_calendar(_fx("macro_fred_calendar_nfp_2026.bin"))
    nov6 = next(t for t in winter if t.date() == D(2026, 11, 6) or t.astimezone(macro.NEW_YORK).date() == D(2026, 11, 6))
    assert nov6.astimezone(macro.UTC) == datetime.datetime(2026, 11, 6, 13, 30, tzinfo=macro.UTC)
    assert nov6.astimezone(macro.NEW_YORK).strftime("%H:%M") == "08:30"


def test_fred_calendar_without_a_time_column_uses_the_default_time_in_eastern():
    html = '<span style="font-weight: bold;">Friday November 06, 2026</span><td>no time here</td>'
    (t,) = macro.parse_fred_release_calendar(html)
    assert t.astimezone(macro.UTC) == datetime.datetime(2026, 11, 6, 13, 30, tzinfo=macro.UTC)
    assert macro.parse_fred_release_calendar("<html>改版了</html>") == []


def test_bea_ics_times_are_utc_and_agree_with_fred_pce_convention():
    pce = macro.parse_bea_ics(_fx("macro_bea_calendar.bin"))
    assert [t for _, t in pce] == [datetime.datetime(2026, 10, 29, 12, 30, tzinfo=macro.UTC),
                                   datetime.datetime(2026, 11, 25, 13, 30, tzinfo=macro.UTC)]
    assert all(t.astimezone(macro.NEW_YORK).strftime("%H:%M") == "08:30" for _, t in pce)
    assert pce[0][0].endswith("September 2026")


def test_census_retail_times_are_eastern():
    times = macro.parse_census_retail(_fx("macro_census_calendar.bin"))
    assert [t.astimezone(macro.NEW_YORK).strftime("%Y-%m-%d %H:%M") for t in times] == [
        "2027-01-15 08:30", "2027-02-17 08:30", "2027-03-16 08:30"]


def test_release_events_nfp_also_yields_unrate_and_sets_series_ids():
    times = macro.parse_fred_release_calendar(_fx("macro_fred_calendar_nfp_2026.bin"))
    rows = macro.release_events("nfp", times, "fred", now=NOW)
    by = {(r["event_type"], r["label"]): r for r in rows}
    nfp, unrate = by[("nfp", "2026-11-06")], by[("unrate", "2026-11-06")]
    assert nfp["series_id"] == "FRED:PAYEMS" and unrate["series_id"] == "FRED:UNRATE"
    assert nfp["event_date"] == D(2026, 11, 6) and nfp["symbol"] == "US" and nfp["status"] == "confirmed"
    assert nfp["released_at"].tzinfo is not None
    assert macro.release_events("cpi", times[:1], "fred", now=NOW)[0]["series_id"] == "FRED:CPIAUCSL"
    assert [r["event_type"] for r in macro.release_events("claims", times[:1], "fred", now=NOW)] == ["claims"]


def test_ism_is_first_us_business_day_and_estimated():
    ev = {r["event_date"]: r for r in macro.ism_events(2025, now=NOW)}
    assert D(2025, 9, 2) in ev and D(2025, 9, 1) not in ev, "勞動節（9/1 週一）順延到 9/2"
    ev27 = {r["event_date"] for r in macro.ism_events(2027, now=NOW)}
    assert D(2027, 1, 4) in ev27 and D(2027, 1, 1) not in ev27 and D(2027, 1, 2) not in ev27, \
        "元旦（週五）之後的週末也要跳過，順延到 1/4"
    rows = macro.ism_events(2026, now=NOW)
    assert len(rows) == 12
    assert {r["status"] for r in rows} == {"estimated"} and {r["source"] for r in rows} == {"rule"}
    assert rows[0]["released_at"].astimezone(macro.NEW_YORK).strftime("%H:%M") == "10:00"


def test_cbc_table_only_has_confirmed_past_meetings():
    today = D(2026, 10, 27)
    assert all(d < today for d in macro.CBC_BOARD_MEETINGS), "未來場次沒有央行公告就不能推算著放"
    rows = macro.cbc_events(now=NOW)
    assert len(rows) == len(macro.CBC_BOARD_MEETINGS)
    assert {r["status"] for r in rows} == {"confirmed"} and "待確認" in rows[0]["time_note"]
    assert rows[0]["released_at"].tzinfo is not None


def test_collect_release_events_falls_back_only_when_fred_has_no_next_pce_and_retail(monkeypatch):
    today = D(2026, 12, 28)   # 12 月下旬：FRED 當年已經沒有下一筆

    def fake_get(url, **k):
        if "fred.stlouisfed.org/releases/calendar" in url:
            return types.SimpleNamespace(text=_fx("macro_fred_calendar_nfp_2026.bin"))  # 全是過去（12-04 之前）
        if "bea.gov" in url:
            return types.SimpleNamespace(text=_fx("macro_bea_calendar.bin"))
        if "census.gov" in url:
            return types.SimpleNamespace(text=_fx("macro_census_calendar.bin"))
        raise AssertionError(url)

    monkeypatch.setattr(macro, "http_get", fake_get)
    rows = macro.collect_release_events(today, now=NOW, out=lambda *_: None)
    assert {r["source"] for r in rows if r["event_type"] == "retail" and r["source"] != "fred"} == {"census"}
    census = [r for r in rows if r["source"] == "census"]
    assert [r["event_date"] for r in census] == [D(2027, 1, 15), D(2027, 2, 17), D(2027, 3, 16)]
    assert not [r for r in rows if r["source"] == "bea"], "BEA 的 PCE 全在今天之前，沒有可補的未來場次"
    assert {"ism", "cbc"} <= {r["event_type"] for r in rows}


def test_collect_release_events_source_failures_only_warn(monkeypatch):
    warns = []

    def boom(url, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(macro, "http_get", boom)
    rows = macro.collect_release_events(D(2026, 10, 27), now=NOW, out=warns.append)
    assert {r["event_type"] for r in rows} == {"ism", "cbc"}, "外部來源全掛，規則日與常數表仍要在"
    assert sum("**WARN" in w for w in warns) == len(macro.RELEASES) + 2


class _ConnEngine:
    """把 pg_conn（外層會 rollback）包成有 ``begin()`` 的 engine，``fill_first_releases`` 才不會真的 commit。"""

    def __init__(self, conn):
        self.conn = conn

    def begin(self):
        import contextlib

        return contextlib.nullcontext(self.conn)


def _release(etype, label, released_at, series="FRED:PAYEMS", source="fred"):
    return {"event_type": etype, "symbol": "US", "label": label, "event_date": released_at.date(),
            "status": "confirmed", "title": f"{etype} test", "time_note": None, "source": source,
            "updated_at": NOW, "released_at": released_at, "series_id": series}


def test_fill_first_releases_is_first_write_wins_and_survives_calendar_refresh(pg_conn):
    """首發值只寫一次；行事曆每天重抓、upsert 也不能把它洗回 NULL。"""
    past = datetime.datetime(1900, 11, 6, 13, 30, tzinfo=datetime.timezone.utc)
    macro.store_events(pg_conn, [_release("nfp", "1900-11-06", past)], D(1900, 11, 1))
    calls = []

    def fetch(code, day):
        calls.append((code, day))
        return {"obs_date": D(1900, 10, 1), "actual": 159350.0, "prior": 159200.0, "vintage": day}

    now = datetime.datetime(1900, 11, 7, tzinfo=datetime.timezone.utc)
    assert macro.fill_first_releases(_ConnEngine(pg_conn), now=now, fetch=fetch, out=lambda *_: None) == 1
    assert calls == [("PAYEMS", D(1900, 11, 6))]
    macro.store_events(pg_conn, [_release("nfp", "1900-11-06", past)], D(1900, 11, 1))   # 行事曆重抓
    # 之後 ALFRED 給了不同的值：已有首發值就不能再改，也不該再去抓
    assert macro.fill_first_releases(_ConnEngine(pg_conn), now=now, out=lambda *_: None,
                                     fetch=lambda c, d: {"obs_date": D(1900, 10, 1), "actual": 1.0,
                                                         "prior": 1.0, "vintage": d}) == 0
    row = pg_conn.execute(text(
        "SELECT actual_value::float, prior_value::float, observation_date, actual_vintage, actual_source "
        "FROM market.event_calendar WHERE symbol = 'US' AND label = '1900-11-06' AND event_type = 'nfp'")).one()
    assert tuple(row) == (159350.0, 159200.0, D(1900, 10, 1), D(1900, 11, 6), "alfred")


def test_fill_first_releases_leaves_null_when_alfred_has_nothing_yet(pg_conn):
    past = datetime.datetime(1900, 11, 6, 13, 30, tzinfo=datetime.timezone.utc)
    future = datetime.datetime(1900, 12, 4, 13, 30, tzinfo=datetime.timezone.utc)
    macro.store_events(pg_conn, [_release("nfp", "1900-11-06", past), _release("nfp", "1900-12-04", future)],
                       D(1900, 11, 1))
    now = datetime.datetime(1900, 11, 7, tzinfo=datetime.timezone.utc)
    seen = []
    assert macro.fill_first_releases(_ConnEngine(pg_conn), now=now, out=lambda *_: None,
                                     fetch=lambda c, d: seen.append(d)) == 0
    assert seen == [D(1900, 11, 6)], "還沒公布的列不抓"


def test_store_events_reschedule_deletes_old_label_only_for_same_type_and_year(pg_conn):
    today = D(2099, 1, 1)
    t = lambda m, d: datetime.datetime(2099, m, d, 13, 30, tzinfo=datetime.timezone.utc)  # noqa: E731
    macro.store_events(pg_conn, [_release("cpi", "2099-03-10", t(3, 10), "FRED:CPIAUCSL"),
                                 _release("cpi", "2099-04-14", t(4, 14), "FRED:CPIAUCSL"),
                                 _release("cpi", "2100-01-13", datetime.datetime(2100, 1, 13, 13, 30,
                                          tzinfo=datetime.timezone.utc), "FRED:CPIAUCSL"),
                                 _release("pce", "2099-03-27", t(3, 27), "FRED:PCEPI")], today)
    # 4/14 改期到 4/15；這次抓取成功（source=fred）→ 同類型同年度未來的舊 label 刪掉，別類型與別年度不動
    macro.store_events(pg_conn, [_release("cpi", "2099-03-10", t(3, 10), "FRED:CPIAUCSL"),
                                 _release("cpi", "2099-04-15", t(4, 15), "FRED:CPIAUCSL")], today)
    rows = pg_conn.execute(text(
        "SELECT event_type, label FROM market.event_calendar WHERE symbol = 'US' AND event_date > '2098-12-31' "
        "ORDER BY 1, 2")).all()
    assert [tuple(r) for r in rows] == [("cpi", "2099-03-10"), ("cpi", "2099-04-15"), ("cpi", "2100-01-13"),
                                        ("pce", "2099-03-27")]


def test_store_events_new_types_never_delete_when_the_fetch_was_not_from_fred(pg_conn):
    """備援（BEA／Census）或規則來源的批次不是權威清單：不能刪任何列。"""
    today = D(2099, 1, 1)
    t = lambda m, d: datetime.datetime(2099, m, d, 13, 30, tzinfo=datetime.timezone.utc)  # noqa: E731
    macro.store_events(pg_conn, [_release("pce", "2099-03-27", t(3, 27), "FRED:PCEPI")], today)
    macro.store_events(pg_conn, [_release("pce", "2099-04-30", t(4, 30), "FRED:PCEPI", source="bea")], today)
    labels = pg_conn.execute(text(
        "SELECT label FROM market.event_calendar WHERE event_type = 'pce' AND symbol = 'US' "
        "AND event_date > '2098-12-31' ORDER BY 1")).scalars().all()
    assert labels == ["2099-03-27", "2099-04-30"]
    # estimated 的規則日不能蓋掉 confirmed
    macro.store_events(pg_conn, [{**_release("pce", "2099-03-27", t(3, 27)), "status": "estimated",
                                  "title": "rule"}], today)
    assert pg_conn.execute(text(
        "SELECT status FROM market.event_calendar WHERE event_type = 'pce' AND label = '2099-03-27'")).scalar() \
        == "confirmed"


def test_fill_first_releases_does_not_overwrite_a_value_written_concurrently(pg_conn):
    """兩個 daily 同時跑：A 讀到 NULL、抓值的空檔 B 已經寫進去；A 的 UPDATE 必須因 IS NULL 條件落空。"""
    past = datetime.datetime(1900, 11, 6, 13, 30, tzinfo=datetime.timezone.utc)
    macro.store_events(pg_conn, [_release("nfp", "1900-11-06", past)], D(1900, 11, 1))

    def racing_fetch(code, day):
        pg_conn.execute(text("UPDATE market.event_calendar SET actual_value = 111 WHERE label = '1900-11-06'"))
        return {"obs_date": D(1900, 10, 1), "actual": 999.0, "prior": 998.0, "vintage": day}

    now = datetime.datetime(1900, 11, 7, tzinfo=datetime.timezone.utc)
    macro.fill_first_releases(_ConnEngine(pg_conn), now=now, fetch=racing_fetch, out=lambda *_: None)
    assert pg_conn.execute(text(
        "SELECT actual_value::float FROM market.event_calendar WHERE label = '1900-11-06'")).scalar() == 111.0
