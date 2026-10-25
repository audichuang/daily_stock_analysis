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

from market_data import crawler, sources

_DAY = date(2026, 10, 22)
_FIXTURE = Path(__file__).parent / "fixtures" / "tpex_otc.json"


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
