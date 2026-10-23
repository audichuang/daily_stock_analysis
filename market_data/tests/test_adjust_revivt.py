"""上櫃減資官方參考價（TPEx bulletin/revivt）與推導備援的參考價選擇。"""

from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import text

from market_data import adjust, sources

FIELDS = ["恢復買賣日期", "股票代號", "名稱", "最後交易日之收盤價格",
          "減資恢復買賣開始日參考價格", "漲停價格", "跌停價格", "開始交易基準價",
          "除權參考價", "減資原因", "詳細資料"]


def _payload(rows, span="20261001~20261023"):
    return {"date": span, "stat": "ok",
            "tables": [{"fields": FIELDS, "totalCount": len(rows), "data": rows}]}


# 3625 的恢復日 10-19：官方 19.86 / 10.10 = 1.966（舊推導用開盤價得 1.792）
ROWS = [["1151019", "3625", "西勝", "10.10", "19.86", "21.8", "17.9", "19.85", "0.00", "彌補虧損", "<x>"],
        ["1151007", "4527", "方土霖", "40.90", "44.33", "48.75", "39.90", "44.35", "0.00", "現金減資", "<x>"]]


def test_parse_revivt_compact_roc_date_and_reference_price():
    df = sources.parse_tpex_revivt(_payload(ROWS))
    r = df[df["stock_id"] == "3625"].iloc[0]
    assert r["date"] == pd.Timestamp("2026-10-19")
    assert (r["close_before"], r["reference_price"]) == (10.10, 19.86)


def test_parse_revivt_all_rows_unparseable_raises():
    with pytest.raises(ValueError):
        sources.parse_tpex_revivt(_payload([["bad", "1", "x", "n/a", "n/a"] + [""] * 6]))


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _crawl(monkeypatch, payload, reason=None):
    monkeypatch.setattr(sources.tw_official_http, "get",
                        lambda *a, **k: (_Resp(payload), reason))
    return sources.crawl_tpex_revivt(date(2026, 10, 1), date(2026, 10, 23))


def test_crawl_revivt_accepts_matching_date(monkeypatch):
    assert len(_crawl(monkeypatch, _payload(ROWS))) == 2


def test_crawl_revivt_rejects_stale_or_mismatched_date(monkeypatch):
    # 端點對不合法參數會靜默退回別的區間：回應日期對不上就當失敗
    assert _crawl(monkeypatch, _payload(ROWS, span="20260101~20260115")) is None


def test_crawl_revivt_http_failure_is_none(monkeypatch):
    assert _crawl(monkeypatch, _payload(ROWS), reason="HTTP 500") is None


def test_fetch_tpex_reductions_factor_and_source(monkeypatch):
    monkeypatch.setattr(sources, "crawl_tpex_revivt",
                        lambda s, e: sources.parse_tpex_revivt(_payload(ROWS)))
    df = adjust.fetch_tpex_reductions(date(2026, 10, 1), date(2026, 10, 23))
    r = df[df["stock_id"] == "3625"].iloc[0]
    assert r["source"] == "tpex_revivt" and r["kind"] == "reduction"
    assert r["factor"] == pytest.approx(19.86 / 10.10)
    # 現金減資跳空 <11%（4527）也要記到
    assert set(df["stock_id"]) == {"3625", "4527"}


def test_refresh_recent_refuses_to_erase_existing_revivt(monkeypatch):
    class _Ctx:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    class _Engine:
        def connect(self):
            return _Ctx()

        def begin(self):
            raise AssertionError("must not start a write transaction")

    existing = pd.DataFrame([{
        "stock_id": "3625", "date": pd.Timestamp("2026-07-15"), "factor": 1.9,
        "kind": "reduction", "source": "tpex_revivt",
        "close_before": 10.0, "reference_price": 19.0}])
    monkeypatch.setattr(adjust, "official_rows", lambda conn: pd.DataFrame())
    monkeypatch.setattr(adjust, "existing_official_rows", lambda conn, start: existing)
    for name in ("fetch_tpex_dividends", "fetch_reductions", "fetch_tpex_reductions"):
        monkeypatch.setattr(adjust, name, lambda *a: pd.DataFrame())
    with pytest.raises(RuntimeError, match="tpex_revivt"):
        adjust.refresh_recent(_Engine(), date(2026, 7, 1), date(2026, 7, 31))


# --- infer_rows 備援：優先 close - change，open 最後備援 ---
FUTURE = date(2100, 1, 4)


def _infer_df(monkeypatch, stock_id, bars, known=frozenset()):
    px = pd.DataFrame([{"stock_id": stock_id, "date": pd.Timestamp(d), "open": o,
                        "close": c, "change": ch} for d, o, c, ch in bars])
    monkeypatch.setattr(adjust.pd, "read_sql", lambda *a, **k: px)
    return adjust.infer_rows(None, set(known), FUTURE)


def _infer(monkeypatch, stock_id, bars):
    """Run infer_rows on in-memory prices (no DB access)."""
    return _infer_df(monkeypatch, stock_id, bars).iloc[0]


def _bars(open_, close, change):
    bars = [(FUTURE + timedelta(days=i), 10.0, 10.0, 0.0) for i in range(8)]
    bars.append((FUTURE + timedelta(days=8), open_, close, change))
    return bars


def test_infer_uses_close_minus_change_as_reference(monkeypatch):
    # 3625 型：open 15.10 對 prev 10.0 算 1.51；官方參考價 16.35 = close 17.0 - change 0.65
    row = _infer(monkeypatch, "1234", _bars(15.10, 17.0, 0.65))
    assert row["reference_price"] == pytest.approx(16.35)
    assert row["factor"] == pytest.approx(1.635)


def test_infer_falls_back_to_open_when_change_missing(monkeypatch):
    row = _infer(monkeypatch, "1235", _bars(15.10, 17.0, None))
    assert row["reference_price"] == pytest.approx(15.10)


def test_infer_ignores_reference_far_from_open(monkeypatch):
    # close - change = 27，離 open 15.10 超過 11%：視為壞資料，退回開盤價
    row = _infer(monkeypatch, "1236", _bars(15.10, 17.0, -10.0))
    assert row["reference_price"] == pytest.approx(15.10)


def _bars_at(gap, price, open_, close, change):
    bars = [(FUTURE + timedelta(days=i), price, price, 0.0) for i in range(8)]
    bars.append((FUTURE + timedelta(days=7 + gap), open_, close, change))
    return bars


def test_infer_change_zero_placeholder_falls_back_to_open(monkeypatch):
    # change=0 是缺值佔位：不可把 close(10.5) 當參考價，否則 factor 0.525 而非 0.5
    row = _infer(monkeypatch, "1237", _bars_at(1, 20.0, 10.0, 10.5, 0.0))
    assert row["reference_price"] == pytest.approx(10.0)
    assert row["factor"] == pytest.approx(0.5)


def test_infer_change_zero_long_gap_split_survives(monkeypatch):
    row = _infer(monkeypatch, "1238", _bars_at(10, 20.0, 10.0, 9.5, 0.0))
    assert row["kind"] == "split" and row["factor"] == pytest.approx(0.5)


def test_infer_nonzero_change_still_used(monkeypatch):
    row = _infer(monkeypatch, "1239", _bars_at(1, 20.0, 10.0, 10.5, 0.5))
    assert row["reference_price"] == pytest.approx(10.0)  # close - change
    row = _infer(monkeypatch, "1240", _bars_at(1, 10.0, 15.10, 17.0, 0.65))
    assert row["reference_price"] == pytest.approx(16.35)


# --- known 事件落在沒有 K 棒的日子 ---
def test_known_event_on_barless_day_explains_next_bar_gap(monkeypatch):
    bars = _bars_at(3, 20.0, 10.0, 10.0, 0.0)
    event_day = FUTURE + timedelta(days=7 + 2)  # 前一根 K 之後、跳空 K 之前，當天無 K
    assert len(_infer_df(monkeypatch, "1241", bars)) == 1
    assert _infer_df(monkeypatch, "1241", bars, {("1241", event_day)}).empty
    # 同日精確命中仍有效
    assert _infer_df(monkeypatch, "1241", bars, {("1241", FUTURE + timedelta(days=10))}).empty


def test_known_event_outside_gap_interval_does_not_explain(monkeypatch):
    bars = _bars_at(3, 20.0, 10.0, 10.0, 0.0)
    before = FUTURE + timedelta(days=3)   # 早於前一根 K（含）
    after = FUTURE + timedelta(days=11)   # 晚於跳空 K
    assert len(_infer_df(monkeypatch, "1242", bars, {("1242", before), ("1242", FUTURE + timedelta(days=7))})) == 1
    assert len(_infer_df(monkeypatch, "1242", bars, {("1242", after)})) == 1
    assert len(_infer_df(monkeypatch, "1242", bars, {("9999", FUTURE + timedelta(days=9))})) == 1
