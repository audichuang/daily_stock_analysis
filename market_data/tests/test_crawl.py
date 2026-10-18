from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from market_data import crawl


def test_crawl_day_institutional_fetch_transform_upsert(pg_conn, monkeypatch):
    # fetch returns finlab-style Chinese columns; crawl should transform+store
    def fake(d):
        # real fetchers return frames indexed by (stock_id, date)
        return pd.DataFrame([{
            "stock_id": "2330", "date": pd.to_datetime(d), "名稱": "台積電",
            "外陸資買賣超股數(不含外資自營商)": 12345, "外資買賣超股數": None,
            "投信買賣超股數": 100, "自營商買賣超股數": 50, "三大法人買賣超股數": 12495,
        }]).set_index(["stock_id", "date"])

    monkeypatch.setattr(crawl.sources, "crawl_institutional", fake)
    n = crawl.crawl_day(pg_conn, "institutional", date(2024, 6, 3))
    assert n == 1
    row = pg_conn.execute(text(
        "SELECT foreign_net, total_net FROM market.institutional "
        "WHERE stock_id='2330' AND date='2024-06-03'"
    )).fetchone()
    assert row == (12345, 12495)


def test_crawl_day_skips_footer_rows(pg_conn, monkeypatch):
    def fake(d):
        return pd.DataFrame([
            {"stock_id": "2330", "date": pd.to_datetime(d), "三大法人買賣超股數": 1},
            {"stock_id": "說明：外陸資不含外資自營商", "date": pd.to_datetime(d),
             "三大法人買賣超股數": None},
        ]).set_index(["stock_id", "date"])

    monkeypatch.setattr(crawl.sources, "crawl_institutional", fake)
    n = crawl.crawl_day(pg_conn, "institutional", date(2024, 6, 4))
    assert n == 1  # footer note row dropped


def test_crawl_day_drops_null_stock_id(pg_conn, monkeypatch):
    # a null stock_id must NOT survive as the string "nan"
    def fake(d):
        return pd.DataFrame([
            {"stock_id": "2330", "date": pd.to_datetime(d), "三大法人買賣超股數": 1},
            {"stock_id": None, "date": pd.to_datetime(d), "三大法人買賣超股數": 2},
        ]).set_index(["stock_id", "date"])

    monkeypatch.setattr(crawl.sources, "crawl_institutional", fake)
    n = crawl.crawl_day(pg_conn, "institutional", date(2024, 6, 5))
    assert n == 1  # null stock_id row dropped, not stored as "nan"
    bad = pg_conn.execute(text(
        "SELECT count(*) FROM market.institutional WHERE stock_id='nan'"
    )).scalar()
    assert bad == 0


def test_price_all_requires_both_markets(monkeypatch):
    twse = pd.DataFrame([{"stock_id": "2330", "date": pd.to_datetime("2024-06-03"),
                          "收盤價": 590.0}]).set_index(["stock_id", "date"])
    otc = pd.DataFrame([{"stock_id": "6488", "date": pd.to_datetime("2024-06-03"),
                         "收盤價": 900.0}]).set_index(["stock_id", "date"])

    # both present -> merged
    monkeypatch.setattr(crawl.crawler, "crawl_price", lambda d: twse)
    monkeypatch.setattr(crawl.sources, "crawl_tpex_price", lambda d: otc)
    out = crawl._price_all(date(2024, 6, 3))
    assert set(out.reset_index()["stock_id"]) == {"2330", "6488"}

    # OTC fetch failed (None) -> skip the whole day, no partial write
    monkeypatch.setattr(crawl.sources, "crawl_tpex_price", lambda d: None)
    assert crawl._price_all(date(2024, 6, 3)) is None


def _revenue_frame(stock_id, revenue, announce="2024-02-10"):
    return pd.DataFrame([{
        "stock_id": stock_id, "date": pd.to_datetime(announce),
        "當月營收": revenue, "去年同月增減(%)": 12.3, "上月比較增減(%)": -1.1,
    }]).set_index(["stock_id", "date"])


def test_crawl_monthly_revenue_derives_month_key(pg_conn, monkeypatch):
    def fake(month, market):
        return _revenue_frame("2330", 2000000) if market == "sii" else None

    monkeypatch.setattr(crawl.crawler, "crawl_monthly_report", fake)
    n = crawl.crawl_monthly_revenue(pg_conn, date(2024, 1, 1))
    assert n == 1
    row = pg_conn.execute(text(
        "SELECT revenue FROM market.monthly_revenue "
        "WHERE stock_id='2330' AND revenue_month='2024-01-01'"  # 營收所屬月
    )).fetchone()
    assert row[0] == 2000000


def test_crawl_monthly_revenue_writes_both_markets_and_survives_one_failing(pg_conn, monkeypatch):
    """上櫃月營收曾整段缺席(彙總報表只抓 /sii/),`screen_tw` 的 YoY 門檻因此把整個上櫃
    靜默篩掉。兩個市場都要抓;而其中一邊抓不到時,另一邊照寫。
    種子用 1900 年:本機 pg_conn 連的是正式庫(rollback 交易),真實列不會落進這個月。"""
    asked = []

    def both(month, market):
        asked.append(market)
        return _revenue_frame("1101" if market == "sii" else "6488",
                              111 if market == "sii" else 222, announce="1900-02-10")

    monkeypatch.setattr(crawl.crawler, "crawl_monthly_report", both)
    assert crawl.crawl_monthly_revenue(pg_conn, date(1900, 1, 1)) == 2
    assert asked == ["sii", "otc"]
    rows = dict(pg_conn.execute(text(
        "SELECT stock_id, revenue FROM market.monthly_revenue "
        "WHERE revenue_month='1900-01-01' AND stock_id IN ('1101','6488')")).fetchall())
    assert rows == {"1101": 111, "6488": 222}

    def otc_down(month, market):
        return _revenue_frame("1101", 333, announce="1900-03-10") if market == "sii" else None

    monkeypatch.setattr(crawl.crawler, "crawl_monthly_report", otc_down)
    assert crawl.crawl_monthly_revenue(pg_conn, date(1900, 2, 1)) == 1


def test_crawl_monthly_report_rejects_unknown_market():
    with pytest.raises(ValueError):
        crawl.crawler.crawl_monthly_report(date(2024, 1, 1), market="tw")


def test_partial_quarter_keeps_evidence_but_forces_a_refetch(tmp_path, monkeypatch):
    """家數不足有**兩個**成因，從錯誤點分不出來：截止日前的半季發布，以及解析器
    對不上新版 markup。所以檔案要留著（後者需要它追查），但要標記，讓下次重跑
    重新下載——不標的話，「目錄已存在則沿用」會讓截止日後的重跑再失敗一次。

    實測 2026-08-09（Q2 截止日 8/14 前 5 天）只有 525 檔申報，去年同季 2582 檔。
    """
    import os

    import pandas as pd

    from market_data import crawl

    monkeypatch.chdir(tmp_path)
    directory = os.path.join("data", "financial_statement", "20262")
    os.makedirs(directory)
    open(os.path.join(directory, "2330.html"), "w").close()

    monkeypatch.setattr(
        crawl.financial_statement, "pack_htmls",
        lambda *a, **k: {"balance_sheet": pd.DataFrame(index=["2330", "2317"])},
    )
    downloads = []
    monkeypatch.setattr(crawl.crawler, "crawl_finance_statement2019",
                        lambda y, s: downloads.append((y, s)) or os.makedirs(directory, exist_ok=True))

    with pytest.raises(RuntimeError, match="looks partial or the parser is out of date"):
        crawl.crawl_financials(object(), 2026, 2)

    assert os.path.isdir(directory), "解析失敗時需要這些檔案追查，不能刪"
    assert os.path.exists(os.path.join(directory, ".partial-quarter")), "沒標記 = 重跑會沿用舊的"
    assert downloads == [], "目錄本來就在，第一次不該重新下載"

    # 重跑：標記在 ⇒ 必須重新下載，而不是沿用那份半季
    with pytest.raises(RuntimeError, match="looks partial"):
        crawl.crawl_financials(object(), 2026, 2)
    assert downloads == [(2026, 2)], "帶標記的目錄沒有觸發重新下載"


class _TxEngine:
    """讓 `refresh_range` 的 `engine.begin()` 落在 pg_conn 那個必定 rollback 的交易裡。"""

    def __init__(self, conn): self.conn = conn
    def begin(self): return self
    def __enter__(self): return self.conn
    def __exit__(self, *a): return False


def _t86(rows):
    return lambda d: pd.DataFrame([{
        "stock_id": sid, "date": pd.to_datetime(d), "名稱": sid,
        "外陸資買賣超股數(不含外資自營商)": f, "外資買賣超股數": None,
        "投信買賣超股數": t, "自營商買賣超股數": 0, "三大法人買賣超股數": f + t,
    } for sid, f, t in rows]).set_index(["stock_id", "date"])


def _seed_institutional(conn, d, rows):
    for sid, f, t in rows:
        conn.execute(text(
            "INSERT INTO market.institutional VALUES (:s, :d, :f, :t, 0, :a)"),
            {"s": sid, "d": d, "f": f, "t": t, "a": f + t})


def _stored(conn, d):
    return {r[0]: (r[1], r[2], r[3]) for r in conn.execute(text(
        "SELECT stock_id, foreign_net, trust_net, total_net FROM market.institutional "
        "WHERE date = :d"), {"d": d})}


def test_refresh_range_replaces_stored_preliminary_day_with_revision(pg_conn, monkeypatch, capsys):
    """T86 18:00 的初版入庫後,官方改了投信、補了一檔外幣 ETF——重抓要整日換成定版。
    種子用 2099 年:本機 pg_conn 連的是正式庫(rollback 交易),真實列不會落進這天。"""
    d = date(2099, 1, 5)
    _seed_institutional(pg_conn, d, [("2330", -100, 3222), ("2454", 50, 7)])
    monkeypatch.setattr(crawl.sources, "crawl_institutional",
                        _t86([("2330", -100, 3235), ("2454", 50, 7), ("00636K", 0, 0)]))

    assert crawl.refresh_range(_TxEngine(pg_conn), "institutional", [d], delay=0) == 1

    assert _stored(pg_conn, d) == {"2330": (-100, 3235, 3135), "2454": (50, 7, 57),
                                   "00636K": (0, 0, 0)}
    out = capsys.readouterr().out
    assert f"**REVISED institutional {d}: 2 rows differ" in out, out


def test_refresh_range_accepts_a_same_size_revision(pg_conn, monkeypatch):
    """最常見的修正是「列數不變、只改數字」(投信欄)。門檻收緊不能把它也擋掉。"""
    d = date(2099, 1, 8)
    _seed_institutional(pg_conn, d, [("2330", -100, 3222), ("2454", 50, 7)])
    monkeypatch.setattr(crawl.sources, "crawl_institutional",
                        _t86([("2330", -100, 3235), ("2454", 50, 7)]))

    assert crawl.refresh_range(_TxEngine(pg_conn), "institutional", [d], delay=0) == 1

    assert _stored(pg_conn, d)["2330"] == (-100, 3235, 3135)


def test_refresh_range_unchanged_day_prints_no_revision(pg_conn, monkeypatch, capsys):
    d = date(2099, 1, 6)
    _seed_institutional(pg_conn, d, [("2330", -100, 3235)])
    monkeypatch.setattr(crawl.sources, "crawl_institutional", _t86([("2330", -100, 3235)]))

    crawl.refresh_range(_TxEngine(pg_conn), "institutional", [d], delay=0)

    assert "**REVISED" not in capsys.readouterr().out


def test_refresh_range_keeps_stored_rows_when_every_fetch_fails(pg_conn, monkeypatch, capsys):
    """被 TWSE 封鎖時(fetch 回 None)不能刪掉既有資料,也不能像 crawl_range 一樣連續零列
    就 raise——重抓失敗不該讓整輪 daily 陪葬。"""
    days = [date(2099, 1, d) for d in (5, 6, 7, 8, 9)]
    for d in days:
        _seed_institutional(pg_conn, d, [("2330", -100, 3222)])
    monkeypatch.setattr(crawl.sources, "crawl_institutional", lambda d: None)

    assert crawl.refresh_range(_TxEngine(pg_conn), "institutional", days, delay=0) == 0

    for d in days:
        assert _stored(pg_conn, d) == {"2330": (-100, 3222, 3122)}
    assert capsys.readouterr().out.count("**WARN refresh institutional") == len(days)


def test_refresh_range_refuses_a_shrunken_response(pg_conn, monkeypatch):
    """TWSE 回過「截斷但非空」的回應。人工 `--force` 容許縮到一半,但每晚無人看守的重抓
    不行:修正只會加列,少了列就是截斷,定版資料不能被它換掉。"""
    d = date(2099, 1, 7)
    _seed_institutional(pg_conn, d, [("2330", -100, 3235), ("2454", 50, 7), ("2317", 1, 1)])
    monkeypatch.setattr(crawl.sources, "crawl_institutional",
                        _t86([("2330", -100, 9999), ("2454", 50, 7)]))

    assert crawl.refresh_range(_TxEngine(pg_conn), "institutional", [d], delay=0) == 0

    assert _stored(pg_conn, d) == {"2330": (-100, 3235, 3135), "2454": (50, 7, 57),
                                   "2317": (1, 1, 2)}


def test_refresh_range_does_not_fetch_days_that_are_not_stored(pg_conn, monkeypatch):
    """缺日歸 crawl_range 補(有連續零列止血);這裡只碰已入庫的日子。"""
    fetched = []
    monkeypatch.setattr(crawl.sources, "crawl_institutional",
                        lambda d: fetched.append(d))

    crawl.refresh_range(_TxEngine(pg_conn), "institutional", [date(2099, 2, 2)], delay=0)

    assert fetched == []


_T86_FIELDS = {
    "foreign_net": "外陸資買賣超股數(不含外資自營商)",
    "trust_net": "投信買賣超股數",
    "dealer_net": "自營商買賣超股數",
    "total_net": "三大法人買賣超股數",
}


def _stored_institutional_rows(conn, d):
    return {r["stock_id"]: r for r in crawl._stored_rows(conn, crawl.models.Institutional.__table__, d)}


@pytest.mark.parametrize("field", _T86_FIELDS)
@pytest.mark.parametrize("refresh", [True, False])
def test_institutional_replace_keeps_rows_on_missing_field(pg_conn, monkeypatch, capsys, field, refresh):
    d = date(2099, 2, 3)
    rows = [("2330", 100, 20), ("2454", 50, 7)]
    _seed_institutional(pg_conn, d, rows)
    raw = _t86(rows)(d).drop(columns=[_T86_FIELDS[field]])
    if field == "foreign_net":
        raw = raw.drop(columns=["外資買賣超股數"])
    monkeypatch.setattr(crawl.sources, "crawl_institutional", lambda d: raw)
    before = _stored_institutional_rows(pg_conn, d)

    n = (crawl.refresh_range(_TxEngine(pg_conn), "institutional", [d], delay=0)
         if refresh else crawl.crawl_day(pg_conn, "institutional", d, replace=True))

    assert n == 0
    assert _stored_institutional_rows(pg_conn, d) == before
    out = capsys.readouterr().out
    assert "**WARN institutional" in out and "degraded payload" in out and field in out
    assert "**REVISED" not in out
    if refresh:
        assert f"**WARN refresh institutional {d}: kept stored rows" in out


@pytest.mark.parametrize("field", _T86_FIELDS)
@pytest.mark.parametrize("nulls, accepted", [(12, False), (5, True)])
def test_institutional_replace_compares_null_share(pg_conn, monkeypatch, capsys, field, nulls, accepted):
    d = date(2099, 2, 4)
    rows = [(str(1000 + i), 100, 20) for i in range(20)]
    _seed_institutional(pg_conn, d, rows)
    # 舊資料本來有 20% 缺值；25% 應放行，60% 必須保留原資料。
    pg_conn.execute(text(f"UPDATE market.institutional SET {field} = NULL "
                         "WHERE date = :d AND stock_id < '1004'"), {"d": d})
    before = _stored_institutional_rows(pg_conn, d)
    raw = _t86(rows)(d)
    raw.iloc[:nulls, raw.columns.get_loc(_T86_FIELDS[field])] = float("nan")
    monkeypatch.setattr(crawl.sources, "crawl_institutional", lambda d: raw)

    assert crawl.refresh_range(_TxEngine(pg_conn), "institutional", [d], delay=0) == int(accepted)
    after = _stored_institutional_rows(pg_conn, d)
    if accepted:
        assert sum(r[field] is None for r in after.values()) == nulls
        assert "degraded payload" not in capsys.readouterr().out
    else:
        assert after == before
        out = capsys.readouterr().out
        assert "degraded payload" in out and field in out
        assert f"**WARN refresh institutional {d}: kept stored rows" in out


def test_institutional_force_replace_repairs_partial_day_with_legacy_foreign_field(pg_conn, monkeypatch):
    d = date(2099, 2, 5)
    _seed_institutional(pg_conn, d, [("2330", 1, 2), ("BAD", 1, 2)])
    raw = _t86([("2330", 100, 20)])(d).drop(columns=["外資買賣超股數"])
    raw = raw.rename(columns={_T86_FIELDS["foreign_net"]: "外資買賣超股數"})
    monkeypatch.setattr(crawl.sources, "crawl_institutional", lambda d: raw)

    assert crawl.crawl_day(pg_conn, "institutional", d, replace=True) == 1
    assert _stored(pg_conn, d) == {"2330": (100, 20, 120)}
