"""官方分割／面額變更來源（TWTCAU、TWTB8U、pvChgRslt、etfSplitRslt）與 adjust 的 dry-run。

事件是固定歷史公告，不適用相對日期；全部用 mock，不寫 DB。
"""

import contextlib
from datetime import date, timedelta

import pandas as pd
import pytest

from market_data import adjust, cli, db, sources

TWTCAU_FIELDS = ["恢復買賣日期", "ETF代號", "名稱", "分割(反分割)", "停止買賣前收盤價格", "恢復買賣參考價",
                 "漲停價格", "跌停價格", "開盤競價基準"]
TWTB8U_FIELDS = ["恢復買賣日期", "股票代號", "名稱", "停止買賣前收盤價格", "恢復買賣參考價",
                 "漲停價格", "跌停價格", "開盤競價基準", "詳細資料"]
TPEX_FIELDS = ["恢復買賣日期", "證券代號", "證券名稱", "最後交易日之收盤價格", "恢復買賣開始參考價",
               "漲停價格", "跌停價格", "開始交易基準價", "詳細資料"]
START, END = date(2025, 1, 1), date(2026, 12, 31)


def _twtcau(rows, start="20250101", end="20261231", stat="OK"):
    return {"stat": stat, "fields": TWTCAU_FIELDS, "data": rows, "startDate": start, "endDate": end}


def _twtb8u(rows, start="20250101", end="20261231"):
    return {"stat": "OK", "params": {"startDate": start, "endDate": end}, "fields": TWTB8U_FIELDS, "data": rows}


def _tpex(rows, span="20250101~20261231", stat="ok"):
    return {"stat": stat, "date": span, "tables": [{"fields": TPEX_FIELDS, "data": rows}]}


def _etf_row(day, sid, kind, before, ref):
    return [day, sid, "名稱", kind, before, ref, "1", "1", ref]


# 官方回應抄錄（00631L 的分割欄是空字串）：(民國日, 代號, 前收, 參考價, 比例)
ETF_EVENTS = [
    ("115/03/31", "00631L", "443.15", "20.14", 1 / 22),
    ("115/07/07", "00685L", "306.00", "12.75", 1 / 24),
    ("114/11/26", "0052", "245.30", "35.04", 1 / 7),
    ("114/06/11", "00663L", "170.15", "24.30", 1 / 7),
    ("114/02/19", "00676R", "2.04", "12.23", 6),
    ("114/10/22", "00673R", "7.02", "28.08", 4),
    ("114/10/22", "00706L", "5.54", "22.16", 4),
    ("114/12/10", "00715L", "10.43", "20.86", 2),
    ("115/04/22", "00674R", "5.18", "25.90", 5),
]


def _crawl_with(monkeypatch, crawl, payload, reason=None):
    class _Resp:
        def json(self):
            return payload
    monkeypatch.setattr(sources.tw_official_http, "get", lambda *a, **k: (_Resp(), reason))
    return crawl(START, END)


def _fetch(monkeypatch, name, df):
    monkeypatch.setattr(sources, name, lambda s, e: df)
    monkeypatch.setattr(adjust, "_fetch_by_year", lambda crawl, s, e, chunk: crawl(s, e))


@pytest.mark.parametrize("day,sid,before,ref,ratio", ETF_EVENTS)
def test_etf_factor_is_official_reference_over_close(monkeypatch, day, sid, before, ref, ratio):
    df = sources.parse_twse_resume(_twtcau([_etf_row(day, sid, "", before, ref)]), START, END,
                                   code="ETF代號", label="TWTCAU")
    _fetch(monkeypatch, "crawl_twse_etf_split", df)
    row = adjust.fetch_official_split("twse_twtcau", START, END).iloc[0]
    assert row["factor"] == pytest.approx(float(ref) / float(before))
    assert row["factor"] == pytest.approx(ratio, rel=2e-3)
    assert (row["kind"], row["source"]) == ("split", "twse_twtcau")


def test_official_factor_is_not_snapped_to_exact_ratio(monkeypatch):
    # 比例一律用官方前收→參考價：0050 是 0.249987，吸附成 1/4 就不是官方值
    df = sources.parse_twse_resume(_twtcau([_etf_row("114/06/18", "0050", "分割", "188.65", "47.16")]), START, END,
                                   code="ETF代號", label="TWTCAU")
    _fetch(monkeypatch, "crawl_twse_etf_split", df)
    factor = adjust.fetch_official_split("twse_twtcau", START, END).iloc[0]["factor"]
    assert factor != 0.25
    assert factor == pytest.approx(47.16 / 188.65, abs=1e-12)


@pytest.mark.parametrize("key,right,wrong", [
    (("00631L", "2026-03-31"), 1 / 22, 1 / 23),
    (("00685L", "2026-07-07"), 1 / 24, 1 / 25),
])
def test_verified_fallback_uses_official_ratio(key, right, wrong):
    assert adjust.VERIFIED_ACTIONS[key] == pytest.approx(right)
    assert adjust.VERIFIED_ACTIONS[key] != pytest.approx(wrong)


@pytest.mark.parametrize("day,sid,before,ref,ratio", [
    ("110/10/18", "6531", "750.00", "375.00", 1 / 2),
    ("113/11/11", "8476", "58.80", "29.40", 1 / 2),
])
def test_twtb8u_par_value_events(monkeypatch, day, sid, before, ref, ratio):
    payload = _twtb8u([[day, sid, "名稱", before, ref, "1", "1", ref, "x"]], "20210101", "20241231")
    df = _crawl_with(monkeypatch, lambda s, e: sources.parse_twse_resume(
        payload, date(2021, 1, 1), date(2024, 12, 31), code="股票代號", label="TWTB8U"), payload)
    assert df.iloc[0]["stock_id"] == sid
    assert df.iloc[0]["reference_price"] / df.iloc[0]["close_before"] == pytest.approx(ratio)


def test_fetch_official_split_accepts_empty_window(monkeypatch):
    monkeypatch.setattr(sources, "crawl_tpex_etf_split", lambda s, e: pd.DataFrame(
        columns=["stock_id", "date", "close_before", "reference_price"]))
    assert adjust.fetch_official_split("tpex_etfsplit", START, START + timedelta(days=30)).empty


def test_fetch_official_split_raises_on_source_failure(monkeypatch):
    monkeypatch.setattr(sources, "crawl_tpex_etf_split", lambda s, e: None)
    with pytest.raises(RuntimeError):
        adjust.fetch_official_split("tpex_etfsplit", START, START + timedelta(days=30))


def test_twse_crawl_accepts_empty_window(monkeypatch):
    df = _crawl_with(monkeypatch, sources.crawl_twse_etf_split, _twtcau([]))
    assert df is not None and df.empty


@pytest.mark.parametrize("payload", [
    _twtcau([_etf_row("115/03/31", "00631L", "", "443.15", "20.14")], start="20240101"),  # 回顯對不上
    _twtcau([_etf_row("113/03/31", "00631L", "", "443.15", "20.14")]),  # 列日期在區間外
    _twtcau([], stat="很抱歉"),
    {"stat": "OK", "fields": TWTCAU_FIELDS, "data": []},  # 沒有回顯
    {**_twtcau([]), "fields": ["改版"]},
])
def test_twse_crawl_rejects_bad_payload(monkeypatch, payload, capsys):
    assert _crawl_with(monkeypatch, sources.crawl_twse_etf_split, payload) is None
    assert "**WARN" in capsys.readouterr().out


def test_twse_crawl_http_failure_is_none(monkeypatch):
    assert _crawl_with(monkeypatch, sources.crawl_twse_etf_split, _twtcau([]), reason="HTTP 500") is None


def test_twtb8u_echo_lives_in_params(monkeypatch):
    assert _crawl_with(monkeypatch, sources.crawl_twse_par_value_change, _twtb8u([])) is not None
    assert _crawl_with(monkeypatch, sources.crawl_twse_par_value_change, _twtb8u([], start="20240101")) is None


def test_unparseable_row_skipped_only_when_others_parse(monkeypatch, capsys):
    good = _etf_row("115/03/31", "00631L", "", "443.15", "20.14")
    bad = _etf_row("115/04/01", "00000X", "", "--", "--")
    df = _crawl_with(monkeypatch, sources.crawl_twse_etf_split, _twtcau([good, bad]))
    assert list(df["stock_id"]) == ["00631L"]
    assert "跳過 1 列" in capsys.readouterr().out
    assert _crawl_with(monkeypatch, sources.crawl_twse_etf_split, _twtcau([bad])) is None


def _tpex_row(day, sid, before, ref):
    return [day, sid, "名稱  ", before, ref, "1", "1", ref, "<table></table>"]


def test_tpex_par_value_compact_roc_date_and_factor(monkeypatch):
    df = _crawl_with(monkeypatch, sources.crawl_tpex_par_value_change,
                     _tpex([_tpex_row("1150309", "8932", "199.50", "99.75")]))
    row = df.iloc[0]
    assert (row["stock_id"], row["date"]) == ("8932", pd.Timestamp("2026-03-09"))
    assert (row["close_before"], row["reference_price"]) == (199.5, 99.75)


def test_tpex_etf_split_empty_is_valid(monkeypatch):
    df = _crawl_with(monkeypatch, sources.crawl_tpex_etf_split, _tpex([]))
    assert df is not None and df.empty


@pytest.mark.parametrize("payload", [
    _tpex([], span="20240101~20241231"),
    _tpex([_tpex_row("1130309", "8932", "199.50", "99.75")]),
    _tpex([], stat="error"),
])
def test_tpex_crawl_rejects_bad_payload(monkeypatch, payload):
    assert _crawl_with(monkeypatch, sources.crawl_tpex_par_value_change, payload) is None


def test_all_split_sources_survive_offline_rebuild():
    # 漏掉任一個，--no-reductions 就會把該來源的官方列清掉
    assert {s for s, _ in adjust.OFFICIAL_SPLIT_SOURCES} <= set(adjust._NETWORK_SOURCES)


# ---- refresh_recent（daily 路徑）----

def _official(sid, day, source, before=100.0, ref=50.0):
    return {"stock_id": sid, "date": pd.Timestamp(day), "factor": ref / before, "kind": "split",
            "source": source, "close_before": before, "reference_price": ref}


class _Conn:
    def execute(self, *a, **k):
        pass


class _Eng:
    @contextlib.contextmanager
    def connect(self):
        yield _Conn()

    @contextlib.contextmanager
    def begin(self):
        yield _Conn()


def _refresh(monkeypatch, split_fetch, existing=(), inferred=None, dividends=()):
    cols = adjust.ADJUSTMENT_COLUMNS
    existing_df = pd.DataFrame(list(existing), columns=cols)
    empty = lambda *a, **k: pd.DataFrame(columns=cols)  # noqa: E731
    seen_known = {}

    def fake_infer(conn, known, start, is_session=None):
        seen_known["known"] = set(known)
        return inferred if inferred is not None else pd.DataFrame(columns=cols)

    monkeypatch.setattr(adjust, "official_rows", lambda conn: empty())
    monkeypatch.setattr(adjust, "existing_official_rows", lambda conn, start: existing_df)
    monkeypatch.setattr(adjust, "fetch_tpex_dividends",
                        lambda *a, **k: pd.DataFrame(list(dividends), columns=cols))
    monkeypatch.setattr(adjust, "fetch_reductions", empty)
    monkeypatch.setattr(adjust, "fetch_tpex_reductions", empty)
    monkeypatch.setattr(adjust, "fetch_official_split", split_fetch)
    monkeypatch.setattr(adjust, "infer_rows", fake_infer)
    rows = []
    monkeypatch.setattr(adjust, "upsert", lambda conn, tbl, recs, keys: rows.extend(recs) or len(recs))
    res = adjust.refresh_recent(_Eng(), date(2026, 6, 1), date(2026, 8, 31))
    return res, rows, seen_known["known"]


def _split_frame(*rows):
    return pd.DataFrame(list(rows), columns=adjust.ADJUSTMENT_COLUMNS)


def test_source_failure_keeps_rows_alerts_and_writes_others(monkeypatch, capsys):
    kept = _official("00685L", "2026-07-07", "twse_twtcau", 306.0, 12.75)
    fresh = _official("5904", "2026-08-10", "tpex_pvchg", 720.0, 72.0)

    def fetch(source, s, e):
        if source == "twse_twtcau":
            raise RuntimeError("TWTCAU 掛了")
        return _split_frame(fresh) if source == "tpex_pvchg" else _split_frame()

    res, rows, _ = _refresh(monkeypatch, fetch, existing=[kept])
    out = capsys.readouterr().out
    assert res["failed_sources"].keys() == {"twse_twtcau"}
    assert {(r["stock_id"], r["source"]) for r in rows} >= {("00685L", "twse_twtcau"), ("5904", "tpex_pvchg")}
    assert f"\n{adjust.ALERT_PREFIX}twse_twtcau" in "\n" + out
    assert next(r for r in rows if r["stock_id"] == "00685L")["factor"] == pytest.approx(12.75 / 306.0)


def test_healthy_refresh_has_no_alert(monkeypatch, capsys):
    res, rows, _ = _refresh(monkeypatch, lambda source, s, e: _split_frame())
    assert res["failed_sources"] == {}
    assert adjust.ALERT_PREFIX not in capsys.readouterr().out


def test_source_omitting_known_event_is_treated_as_failure(monkeypatch, capsys):
    kept = _official("00685L", "2026-07-07", "twse_twtcau", 306.0, 12.75)
    res, rows, _ = _refresh(monkeypatch, lambda source, s, e: _split_frame(), existing=[kept])
    assert "twse_twtcau" in res["failed_sources"]
    assert [r["stock_id"] for r in rows] == ["00685L"]
    assert adjust.ALERT_PREFIX in capsys.readouterr().out


def test_official_beats_verified_and_inferred_same_day(monkeypatch):
    official = _official("00631L", "2026-07-01", "twse_twtcau", 443.15, 20.14)
    monkeypatch.setitem(adjust.VERIFIED_ACTIONS, ("00631L", "2026-07-01"), 1 / 23)
    inferred = _split_frame(_official("00631L", "2026-07-01", "inferred_price", 100.0, 10.0))
    _, rows, known = _refresh(
        monkeypatch, lambda source, s, e: _split_frame(official) if source == "twse_twtcau" else _split_frame(),
        inferred=inferred)
    row = [r for r in rows if r["stock_id"] == "00631L"]
    assert len(row) == 1 and row[0]["source"] == "twse_twtcau"
    assert row[0]["factor"] == pytest.approx(20.14 / 443.15)
    assert ("00631L", pd.Timestamp("2026-07-01")) in known


def test_verified_used_when_official_source_is_down(monkeypatch):
    # 反向：官方掛掉且 DB 還沒有列時，不能連備援都丟掉（ETF 不會被推導補回）
    monkeypatch.setitem(adjust.VERIFIED_ACTIONS, ("00631L", "2026-07-01"), 1 / 22)

    def fetch(source, s, e):
        raise RuntimeError("down")

    _, rows, _ = _refresh(monkeypatch, fetch)
    assert [(r["stock_id"], r["source"]) for r in rows if r["stock_id"] == "00631L"] == [("00631L", "verified_manual")]


def test_official_split_on_barless_day_explains_next_bar():
    """事件日該檔沒成交：跳空在下一根 K，不能再推一筆（否則同事件算兩次）；無關的跳空仍要推。"""
    days = [d for d in pd.bdate_range("2099-01-05", periods=12)]
    event = days[9]
    px = pd.DataFrame([{"stock_id": "2330", "date": d, "open": 100.0 if d < event else 50.0,
                        "high": 100.0 if d < event else 50.0, "low": 100.0 if d < event else 50.0,
                        "close": 100.0 if d < event else 50.0, "change": 0.0}
                       for d in days if d != event])
    original = adjust.pd.read_sql
    adjust.pd.read_sql = lambda *a, **k: px.copy()
    try:
        assert adjust.infer_rows(None, {("2330", event)}, date(2099, 1, 1), is_session=lambda d: True).empty
        assert len(adjust.infer_rows(None, set(), date(2099, 1, 1), is_session=lambda d: True)) == 1
    finally:
        adjust.pd.read_sql = original


# ---- rebuild／dry-run ----

def _rebuild_mocks(monkeypatch, split_fetch, stored=()):
    cols = adjust.ADJUSTMENT_COLUMNS
    nonempty = lambda s, e, **k: pd.DataFrame(  # noqa: E731
        [_official("1111", "2026-01-05", "x")], columns=cols)
    monkeypatch.setattr(adjust, "official_rows", lambda conn: pd.DataFrame(columns=cols))
    monkeypatch.setattr(adjust, "fetch_tpex_dividends", nonempty)
    monkeypatch.setattr(adjust, "fetch_reductions", nonempty)
    monkeypatch.setattr(adjust, "fetch_tpex_reductions", nonempty)
    monkeypatch.setattr(adjust, "fetch_official_split", split_fetch)
    monkeypatch.setattr(adjust, "existing_official_rows",
                        lambda conn, start: pd.DataFrame(list(stored), columns=cols))
    monkeypatch.setattr(adjust, "infer_rows", lambda conn, known, start: pd.DataFrame(columns=cols))


class _NoWriteEng(_Eng):
    def begin(self):
        raise AssertionError("must not open a write transaction")


def test_rebuild_accepts_empty_split_source(monkeypatch):
    # 上櫃 ETF 分割全期 0 列是常態，不能套舊來源的「空就 raise」
    _rebuild_mocks(monkeypatch, lambda source, s, e: _split_frame())
    final, _ = adjust._rebuild_frames(_Eng(), date(2013, 1, 1))
    assert "1111" in set(final["stock_id"])


def test_rebuild_raises_on_split_failure_before_writing(monkeypatch):
    def fail(source, s, e):
        raise RuntimeError("down")
    _rebuild_mocks(monkeypatch, fail)
    with pytest.raises(RuntimeError, match="down"):
        adjust.rebuild(_NoWriteEng(), start="2013-01-01")


def test_rebuild_refuses_to_lose_known_official_split(monkeypatch):
    stored = [_official("00631L", "2026-03-31", "twse_twtcau", 443.15, 20.14)]
    _rebuild_mocks(monkeypatch, lambda source, s, e: _split_frame(), stored)
    with pytest.raises(RuntimeError, match="twse_twtcau"):
        adjust.rebuild(_NoWriteEng(), start="2013-01-01")


def test_rebuild_fetches_announced_future_events(monkeypatch):
    # 只抓到今天的話，已公告的未來事件（實例 4207 11-09 上櫃減資）會被重建刪掉
    ends = {}

    def record(key, frame):
        def fetch(s, e):
            ends.setdefault(key, []).append((s, e))
            return frame
        return fetch

    row = pd.DataFrame([_official("1111", "2026-01-05", "x")], columns=adjust.ADJUSTMENT_COLUMNS)
    _rebuild_mocks(monkeypatch, lambda source, s, e: record(source, _split_frame())(s, e))
    monkeypatch.setattr(adjust, "fetch_tpex_dividends", record("div", row))
    monkeypatch.setattr(adjust, "fetch_reductions", record("red", row))
    monkeypatch.setattr(adjust, "fetch_tpex_reductions", record("revivt", row))
    adjust._rebuild_frames(_Eng(), date(2013, 1, 1))
    today = date.today()
    window = timedelta(days=adjust.ADJUSTMENT_WINDOW_DAYS)
    assert len(ends) == 7
    for spans in ends.values():
        # 歷史一段、未來一段；不可把 2013 起的逐年切段延到未來（全在未來的那段 TWTAUU 回非 OK）
        assert spans == [(date(2013, 1, 1), today), (today - window, today + window)]


def test_with_announced_prefers_recent_fetch_and_keeps_history():
    old = pd.DataFrame([_official("1", "2020-01-02", "x"), _official("2", "2026-01-05", "x", 100.0, 50.0)])
    new = pd.DataFrame([_official("2", "2026-01-05", "x", 100.0, 40.0), _official("3", "2026-11-09", "x")])
    got = adjust._with_announced(lambda s, e: old if e == date.today() else new, date(2013, 1, 1))
    assert sorted(got["stock_id"]) == ["1", "2", "3"]
    assert got[got["stock_id"] == "2"].iloc[0]["reference_price"] == 40.0


def _row(sid, day, factor, source, before=None, ref=None, kind="split"):
    return {"stock_id": sid, "date": pd.Timestamp(day), "factor": factor, "kind": kind, "source": source,
            "close_before": before, "reference_price": ref}


def test_classify_changes_buckets():
    cols = adjust.ADJUSTMENT_COLUMNS
    current = pd.DataFrame([
        _row("00631L", "2026-03-31", 1 / 23, "verified_manual"),
        _row("6548", "2019-09-09", 0.1, "inferred_price", 312.0, 31.2),
        _row("2330", "2026-06-11", 0.99, "twse_twt49u", 100.0, 99.0, "dividend"),
        _row("9999", "2025-01-02", 0.5, "inferred_price", 10.0, 5.0),
        _row("1101", "2012-01-02", 0.9, "twse_twt49u", 10.0, 9.0, "dividend"),
    ], columns=cols)
    final = pd.DataFrame([
        _row("00631L", "2026-03-31", 20.14 / 443.15, "twse_twtcau", 443.15, 20.14),
        _row("6548", "2019-09-09", 0.1, "tpex_pvchg", 312.0, 31.2),
        _row("2330", "2026-06-11", 0.99, "twse_twt49u", 100.0, 99.0, "dividend"),
        _row("0052", "2025-11-26", 35.04 / 245.3, "twse_twtcau", 245.3, 35.04),
    ], columns=cols)
    got = adjust.classify_changes(current, final, date(2013, 1, 1))
    assert list(got["added"]["stock_id"]) == ["0052"]
    assert list(got["changed"]["stock_id"]) == ["00631L"]
    assert got["changed"].iloc[0]["old_factor"] == pytest.approx(1 / 23)
    assert list(got["meta_changed"]["stock_id"]) == ["6548"]
    assert list(got["deleted"]["stock_id"]) == ["9999"]  # 1101 在 start 之前，重建不動
    assert list(got["unchanged"]["stock_id"]) == ["2330"]


def test_restored_returns_00631l_matches_official_change():
    # 恢復日官方漲跌 -0.88（收 19.26 對參考價 20.14），還原後應是 -4.37%；舊因子 1/23 把它抹成約 0
    px = pd.DataFrame({"stock_id": "00631L", "date": pd.to_datetime(["2026-03-20", "2026-03-31"]),
                       "close": [443.15, 19.26]})
    old = pd.DataFrame([_row("00631L", "2026-03-31", 1 / 23, "verified_manual")])
    new = pd.DataFrame([_row("00631L", "2026-03-31", 20.14 / 443.15, "twse_twtcau")])
    events = pd.DataFrame({"stock_id": ["00631L"], "date": [pd.Timestamp("2026-03-31")]})
    row = adjust.restored_returns(px, old, new, events).iloc[0]
    assert row["event_ret_old"] == pytest.approx(19.26 / (443.15 / 23) - 1)
    assert row["event_ret_new"] == pytest.approx(19.26 / 20.14 - 1)
    assert abs(row["event_ret_old"]) < 0.001


def test_official_same_day_overlap_ignores_manual_and_inferred():
    cols = adjust.ADJUSTMENT_COLUMNS
    a = pd.DataFrame([_row("1", "2026-01-05", 0.9, "twse_twt49u"), _row("2", "2026-01-05", 0.9, "twse_twt49u")], columns=cols)
    b = pd.DataFrame([_row("1", "2026-01-05", 0.5, "twse_twtb8u"), _row("3", "2026-01-05", 0.5, "twse_twtb8u")], columns=cols)
    c = pd.DataFrame([_row("3", "2026-01-05", 0.5, "verified_manual"), _row("2", "2026-01-05", 0.5, "inferred_price")], columns=cols)
    got = adjust.official_same_day_overlap([a, b, c])
    assert set(got["stock_id"]) == {"1"} and len(got) == 2


def test_dry_run_never_opens_write_transaction_and_prints_buckets(monkeypatch, capsys):
    cols = adjust.ADJUSTMENT_COLUMNS
    final = pd.DataFrame([_row("00631L", "2026-03-31", 20.14 / 443.15, "twse_twtcau", 443.15, 20.14)], columns=cols)
    current = pd.DataFrame([_row("00631L", "2026-03-31", 1 / 23, "verified_manual")], columns=cols)
    px = pd.DataFrame({"stock_id": "00631L", "date": pd.to_datetime(["2026-03-20", "2026-03-31"]),
                       "close": [443.15, 19.26]})
    monkeypatch.setattr(adjust, "_rebuild_frames", lambda eng, s, w: (final, [final]))
    monkeypatch.setattr(adjust.pd, "read_sql",
                        lambda sql, conn, **k: px if "market.price " in str(sql) + " " and "adjustment" not in str(sql) else current)
    adjust.print_dry_run(adjust.dry_run(_NoWriteEng()))
    out = capsys.readouterr().out
    assert "修改（因子變動）1" in out and "00631L" in out and "-4.37%" in out
    assert "新增 0" in out and "刪除 0" in out


def test_read_only_engine_sets_session_default(monkeypatch):
    seen = {}
    monkeypatch.setattr(db, "create_engine", lambda url, **k: seen.update(k))
    db._engine_for.cache_clear()
    db.get_engine("postgresql://x/ro", read_only=True, statement_timeout_ms=5)
    assert "default_transaction_read_only=on" in seen["connect_args"]["options"]
    assert "statement_timeout=5" in seen["connect_args"]["options"]
    db.get_engine("postgresql://x/rw")
    assert "options" not in seen["connect_args"]
    db._engine_for.cache_clear()


@pytest.mark.parametrize("argv,read_only,called", [
    (["adjust", "--dry-run"], True, "dry_run"),
    (["adjust"], False, "rebuild"),
])
def test_cli_dry_run_routes_to_read_only_and_never_rebuilds(monkeypatch, argv, read_only, called):
    calls = []
    monkeypatch.setattr(cli, "get_engine", lambda read_only=False: calls.append(read_only) or object())
    monkeypatch.setattr(adjust, "dry_run", lambda *a, **k: calls.append("dry_run") or {})
    monkeypatch.setattr(adjust, "print_dry_run", lambda *a, **k: None)
    monkeypatch.setattr(adjust, "rebuild",
                        lambda *a, **k: calls.append("rebuild") or {"written": 0})
    cli.main(argv)
    assert calls == [read_only, called]
