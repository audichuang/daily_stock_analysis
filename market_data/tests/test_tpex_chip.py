"""上櫃（TPEx）三大法人／融資融券／估值：解析與「依市場分開」的 resume／replace。"""

import json
import pathlib
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from market_data import crawl, etl, sources

_FX = pathlib.Path(__file__).parent / "fixtures"
_DAY = date(2026, 8, 28)


def _load(name):
    return json.loads((_FX / name).read_text())


def test_tpex_institutional_maps_to_t86_columns():
    raw = sources.parse_tpex_institutional(_load("tpex_insti.json"), _DAY)
    out = etl.transform_institutional(raw.reset_index()).set_index("stock_id")
    # 3324 雙鴻 2026-08-28：外資(不含外資自營商) 1,596,703、投信 460,000、
    # 自營商合計 116,676、三大法人合計 2,173,379（官網同日數字）
    assert out.loc["3324", ["foreign_net", "trust_net", "dealer_net", "total_net"]].tolist() == [
        1596703, 460000, 116676, 2173379]


def test_tpex_institutional_rejects_shifted_header():
    payload = _load("tpex_insti.json")
    payload["tables"][0]["fields"].insert(5, "新欄位")
    with pytest.raises(ValueError, match="表頭"):
        sources.parse_tpex_institutional(payload, _DAY)


def test_tpex_margin_maps_to_mi_margn_columns():
    raw = sources.parse_tpex_margin(_load("tpex_margin.json"), _DAY)
    out = etl.transform_margin(raw.reset_index()).set_index("stock_id")
    row = out.loc["3324"]
    assert [row[c] for c in ("margin_balance", "margin_buy", "margin_sell",
                             "short_balance", "short_buy", "short_sell")] == [4703, 692, 660, 48, 9, 17]


def test_tpex_valuation_by_name_and_na_is_null():
    df = sources.parse_tpex_valuation(_load("tpex_pe.json"), _DAY)
    assert df.loc[("3324", pd.Timestamp(_DAY))].tolist() == [26.29, 8.0, 1.04]
    assert df["pe_ratio"].isna().any(), "fixture 帶一列本益比 N/A，應轉成 NULL"


def test_tpex_valuation_refuses_null_wash():
    payload = _load("tpex_pe.json")
    idx = payload["tables"][0]["fields"].index("股價淨值比")
    for r in payload["tables"][0]["data"]:
        r[idx] = "N/A"
    with pytest.raises(ValueError, match="NULL"):
        sources.parse_tpex_valuation(payload, _DAY)


@pytest.mark.parametrize("parse,fx", [
    (sources.parse_tpex_institutional, "tpex_insti.json"),
    (sources.parse_tpex_margin, "tpex_margin.json"),
    (sources.parse_tpex_valuation, "tpex_pe.json"),
])
def test_tpex_unpublished_or_wrong_date_returns_none(parse, fx):
    empty = _load(fx)
    empty["tables"][0]["data"] = []          # 未發布：日期照回請求日、0 列
    assert parse(empty, _DAY) is None
    assert parse(_load(fx), date(2026, 8, 27)) is None   # 回應日期 ≠ 請求日
    stale = _load(fx)
    stale["tables"][0]["date"] = "115/08/27"             # 外層照填請求日、表卻是前一日的舊表
    assert parse(stale, _DAY) is None
    del stale["tables"][0]["date"]                       # 表沒帶日期：證明不了新鮮，拒收
    assert parse(stale, _DAY) is None
    assert parse(_load(fx), _DAY) is not None            # 反向：日期一致照常解析


# --- DB：上市／上櫃同日共存，replace 與 resume 只碰自己的市場 ---------------------

_D = date(2099, 3, 3)   # 遠離真實資料（本機 pg_conn 連正式庫，交易會 rollback）


def _seed(conn):
    conn.execute(text("INSERT INTO market.institutional (stock_id, date, foreign_net, total_net) "
                      "VALUES ('2330', :d, 1, 1)"), {"d": _D})
    conn.execute(text("INSERT INTO market.institutional (stock_id, date, foreign_net, total_net, market) "
                      "VALUES ('3324', :d, 2, 2, 'tpex')"), {"d": _D})


def _rows(conn):
    return dict(conn.execute(text(
        "SELECT stock_id, coalesce(market, 'twse') FROM market.institutional WHERE date = :d"),
        {"d": _D}).fetchall())


def _frame(sid, n):
    return lambda d: pd.DataFrame([{
        "stock_id": sid, "date": pd.to_datetime(d), "名稱": sid,
        "外陸資買賣超股數(不含外資自營商)": n, "外資買賣超股數": None,
        "投信買賣超股數": 0, "自營商買賣超股數": 0, "三大法人買賣超股數": n,
    }]).set_index(["stock_id", "date"])


def test_twse_replace_keeps_same_day_tpex_rows(pg_conn, monkeypatch):
    _seed(pg_conn)
    monkeypatch.setattr(crawl.sources, "crawl_institutional", _frame("2330", 9))
    assert crawl.crawl_day(pg_conn, "institutional", _D, replace=True) == 1
    assert _rows(pg_conn) == {"2330": "twse", "3324": "tpex"}


def test_tpex_replace_keeps_same_day_twse_rows_and_tags_market(pg_conn, monkeypatch):
    _seed(pg_conn)
    monkeypatch.setattr(crawl.sources, "crawl_tpex_chip", lambda kind, d: _frame("6488", 5)(d))
    assert crawl.crawl_day(pg_conn, "institutional_tpex", _D, replace=True) == 1
    # 3324 是被換掉的上櫃舊列；2330 上市列不能陪葬
    assert _rows(pg_conn) == {"2330": "twse", "6488": "tpex"}


def test_resume_sees_each_market_separately(pg_conn):
    pg_conn.execute(text("INSERT INTO market.institutional (stock_id, date, market) "
                         "VALUES ('3324', :d, 'tpex')"), {"d": _D})
    assert _D.isoformat() in crawl._existing_dates(pg_conn, "institutional", "tpex")
    assert _D.isoformat() not in crawl._existing_dates(pg_conn, "institutional")


def test_every_tpex_source_is_market_tagged():
    # 新增 *_tpex 來源卻漏了 SOURCE_MARKET，就會以 NULL（＝上市）寫入並被上市 replace 刪掉
    assert {s for s in crawl.DAILY if s.endswith("_tpex")} == set(crawl.SOURCE_MARKET)
    assert set(crawl.SOURCE_MARKET.values()) == {"tpex"}



def test_crawl_day_tpex_collision_does_not_overwrite_listed_row(pg_conn, monkeypatch, capsys):
    """上櫃來源吐出與上市撞號的代號（實例：006201 → '6201'）：不能整列蓋掉上市列並改標 tpex。"""
    _seed(pg_conn)
    monkeypatch.setattr(crawl.sources, "crawl_tpex_chip", lambda kind, d: _frame("2330", 9)(d))
    assert crawl.crawl_day(pg_conn, "institutional_tpex", _D) == 0
    assert _rows(pg_conn) == {"2330": "twse", "3324": "tpex"}
    assert pg_conn.execute(text("SELECT foreign_net FROM market.institutional "
                                "WHERE stock_id = '2330' AND date = :d"), {"d": _D}).scalar() == 1
    assert "**WARN institutional: 1 rows skipped" in capsys.readouterr().out


# --- crawl_range／refresh_range 的 resume 要依市場判斷「這天做過了沒」----------------

class _TxEngine:
    def __init__(self, conn): self.conn = conn
    def begin(self): return self
    def __enter__(self): return self.conn
    def __exit__(self, *a): return False


def _calendar_day(conn):
    # crawl_range 只抓 market.price 有的交易日
    conn.execute(text("INSERT INTO market.price (stock_id, date) VALUES ('2330', :d)"), {"d": _D})


def _recording_fetch(monkeypatch, calls):
    def fetch(*args):
        calls.append(args)
        return _frame("6488", 5)(args[-1])
    monkeypatch.setattr(crawl.sources, "crawl_tpex_chip", fetch)
    monkeypatch.setattr(crawl.sources, "crawl_institutional", fetch)


@pytest.mark.parametrize("stored, source, fetched", [
    ("twse", "institutional_tpex", True),    # 只有上市列：上櫃這天還沒做
    ("tpex", "institutional_tpex", False),   # 上櫃已入庫：resume 跳過
    ("tpex", "institutional", True),         # 只有上櫃列：上市這天還沒做
    ("twse", "institutional", False),
])
def test_crawl_range_resume_is_per_market(pg_conn, monkeypatch, stored, source, fetched):
    _calendar_day(pg_conn)
    pg_conn.execute(text("INSERT INTO market.institutional (stock_id, date, market) "
                         "VALUES ('3324', :d, :m)"), {"d": _D, "m": None if stored == "twse" else "tpex"})
    calls = []
    _recording_fetch(monkeypatch, calls)
    crawl.crawl_range(_TxEngine(pg_conn), source, [_D], resume=True)
    assert bool(calls) is fetched


@pytest.mark.parametrize("stored, fetched", [("twse", False), ("tpex", True)])
def test_refresh_range_tpex_only_refreshes_stored_tpex_days(pg_conn, monkeypatch, stored, fetched):
    pg_conn.execute(text("INSERT INTO market.institutional (stock_id, date, market) "
                         "VALUES ('3324', :d, :m)"), {"d": _D, "m": None if stored == "twse" else "tpex"})
    calls = []
    _recording_fetch(monkeypatch, calls)
    crawl.refresh_range(_TxEngine(pg_conn), "institutional_tpex", [_D], delay=0)
    assert bool(calls) is fetched
