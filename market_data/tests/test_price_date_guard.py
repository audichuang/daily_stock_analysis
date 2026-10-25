"""每日股價爬蟲必須核對回應自帶的資料日（審查 M3）。

TWSE／TPEx 對非交易日、尚未發布或凍結的日子會回 HTTP 200 加上**別天的表**；舊版直接把列
蓋上請求日，寫進一個不存在的交易日、resume 也不會再重試。比照 T86／MI_MARGN／TPEx 籌碼：
日期不符或缺日期一律拒收（回 None）。每個拒收測試都配一個「日期相符照收」的反向守門。
"""

import copy
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from market_data import crawler, sources

_DAY = date(2026, 10, 22)
_FIXTURE = Path(__file__).parent / "fixtures" / "tpex_otc.json"
_INVALID_TITLE_DATES = [
    pytest.param("115年02月30日", id="invalid-day"),
    pytest.param("115年13月22日", id="invalid-month"),
    pytest.param("10000年10月22日", id="out-of-range-year"),
    pytest.param("100000000000年10月22日", id="overflowing-year"),
]


def _tpex_raw(mutate=None):
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    if mutate:
        payload = copy.deepcopy(payload)
        mutate(payload)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


# --- TPEx afterTrading/otc ---------------------------------------------------


def test_tpex_price_matching_date_is_accepted():
    df = sources.parse_tpex_price(_tpex_raw(), _DAY)
    assert df is not None and len(df) == 2
    assert df.at[("6488", pd.Timestamp(_DAY)), "收盤價"] == 420.0


def test_tpex_price_previous_day_payload_is_rejected(capsys):
    def prev(p):
        p["date"] = "20261021"
        p["tables"][0]["date"] = "115/10/21"
    assert sources.parse_tpex_price(_tpex_raw(prev), _DAY) is None
    assert "拒收" in capsys.readouterr().out


def test_tpex_price_stale_table_under_echoed_outer_date_is_rejected():
    """外層照填請求日、表本身卻是前一天：只看外層擋不住。"""
    def stale(p):
        p["tables"][0]["date"] = "115/10/21"
    assert sources.parse_tpex_price(_tpex_raw(stale), _DAY) is None


def test_tpex_price_wrong_outer_date_is_rejected():
    def outer(p):
        p["date"] = "20261021"
    assert sources.parse_tpex_price(_tpex_raw(outer), _DAY) is None


def test_tpex_price_missing_dates_are_rejected():
    def no_outer(p):
        del p["date"]

    def no_table(p):
        del p["tables"][0]["date"]
    assert sources.parse_tpex_price(_tpex_raw(no_outer), _DAY) is None
    assert sources.parse_tpex_price(_tpex_raw(no_table), _DAY) is None


def test_crawl_tpex_price_returns_none_on_stale_payload(monkeypatch):
    class _R:
        def __init__(self, content):
            self.content = content
            self.text = content.decode("utf-8")

    def stale(p):
        p["date"] = "20261021"
        p["tables"][0]["date"] = "115/10/21"
    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: _R(_tpex_raw(stale)))
    assert sources.crawl_tpex_price(_DAY) is None
    # 反向：同一路徑日期相符要照收
    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: _R(_tpex_raw()))
    assert len(sources.crawl_tpex_price(_DAY)) == 2


@pytest.mark.parametrize("kind,fixture,day", [
    ("price", "tpex_otc.json", _DAY),
    ("institutional", "tpex_insti.json", date(2026, 8, 28)),
    ("margin", "tpex_margin.json", date(2026, 8, 28)),
    ("valuation", "tpex_pe.json", date(2026, 8, 28)),
], ids=["price", "institutional", "margin", "valuation"])
def test_tpex_overflowing_table_date_is_rejected(monkeypatch, capsys, kind, fixture, day):
    payload = json.loads((_FIXTURE.parent / fixture).read_text(encoding="utf-8"))
    table_date = payload["tables"][0]["date"]

    class _R:
        status_code = 200

        def __init__(self):
            self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.text = self.content.decode("utf-8")

        def json(self):
            return json.loads(self.content)

    monkeypatch.setattr(sources, "requests_get", lambda *a, **k: _R())
    crawl = sources.crawl_tpex_price if kind == "price" else lambda d: sources.crawl_tpex_chip(kind, d)
    payload["tables"][0]["date"] = "100000000000/10/22"
    assert crawl(day) is None
    warning = capsys.readouterr().out
    assert "**WARN: TPEx" in warning and "拒收" in warning
    # 反向：原始的相符日期仍須解析成功，不能把所有資料一律拒收。
    payload["tables"][0]["date"] = table_date
    df = crawl(day)
    assert df is not None and len(df)
    assert set(df.index.get_level_values("date")) == {pd.Timestamp(day)}


# --- TWSE MI_INDEX csv ---------------------------------------------------------

_HEADER = (
    '"證券代號","證券名稱","成交股數","成交筆數","成交金額","開盤價","最高價",'
    '"最低價","收盤價","漲跌(+/-)","漲跌價差","最後揭示買價","最後揭示買量",'
    '"最後揭示賣價","最後揭示賣量","本益比",'
)
_ROW = (
    '="2330","台積電","17,227,480","30,000","41,248,293,420","2,375.00","2,410.00",'
    '"2,365.00","2,350.00","-","30.00","2,349.00","100","2,350.00","100","25.00",'
)


class _Resp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200


def _twse(monkeypatch, title):
    body = "\n".join([title, '"指數","收盤指數"', _HEADER, _ROW])
    monkeypatch.setattr(crawler, "_request", lambda *a, **k: _Resp(body))
    return crawler.crawl_price(_DAY)


def test_twse_price_matching_title_date_is_accepted(monkeypatch):
    df = _twse(monkeypatch, '"115年10月22日 價格指數(臺灣證券交易所)"')
    assert df is not None
    assert df.at[("2330", pd.Timestamp(_DAY)), "收盤價"] == 2350.0


def test_twse_price_previous_day_title_is_rejected(monkeypatch, capsys):
    assert _twse(monkeypatch, '"115年10月21日 價格指數(臺灣證券交易所)"') is None
    assert "MI_INDEX" in capsys.readouterr().out


def test_twse_price_title_without_date_is_rejected(monkeypatch):
    assert _twse(monkeypatch, '"價格指數(臺灣證券交易所)"') is None


@pytest.mark.parametrize("title_date", _INVALID_TITLE_DATES)
def test_twse_price_invalid_title_date_is_rejected(monkeypatch, capsys, title_date):
    assert _twse(monkeypatch, f'"{title_date} 價格指數(臺灣證券交易所)"') is None
    warning = capsys.readouterr().out
    assert "**WARN: MI_INDEX" in warning and "拒收" in warning
    # 反向：不能因拒收無效日期，就連相符日期也一起擋掉。
    df = _twse(monkeypatch, '"115年10月22日 價格指數(臺灣證券交易所)"')
    assert df.at[("2330", pd.Timestamp(_DAY)), "收盤價"] == 2350.0


@pytest.mark.parametrize("crawl,report,body,column,value", [
    (sources.crawl_institutional, "T86",
     '"證券代號","證券名稱","外陸資買賣超股數(不含外資自營商)"\n"2330","台積電","12,345"',
     "外陸資買賣超股數(不含外資自營商)", 12345),
    (sources.crawl_margin, "MI_MARGN",
     '"代號","名稱","買進","賣出","現金償還","前日餘額","今日餘額","次一營業日限額",'
     '"買進","賣出","現券償還","前日餘額","今日餘額","次一營業日限額","資券互抵","註記",\n'
     '"2330","台積電","10","20","0","1,000","1,100","5,000","1","2","0","30","31","500","0"," ",',
     "融資今日餘額", 1100),
], ids=["T86", "MI_MARGN"])
@pytest.mark.parametrize("title_date", _INVALID_TITLE_DATES)
def test_twse_chip_invalid_title_date_is_rejected(
    monkeypatch, capsys, crawl, report, body, column, value, title_date,
):
    raw = f'"{title_date} {report}"\r\n{body}'.encode("big5")
    monkeypatch.setattr(sources, "_twse_csv", lambda url: raw)
    assert crawl(_DAY) is None
    warning = capsys.readouterr().out
    assert f"**WARN: {report}" in warning and "拒收" in warning
    # 反向：相同 Big5 資料只換成相符日期，必須經過真正的 parser 並保留數值。
    raw = f'"115年10月22日 {report}"\r\n{body}'.encode("big5")
    df = crawl(_DAY)
    assert df.at[("2330", pd.Timestamp(_DAY)), column] == value
