# -*- coding: utf-8 -*-
"""TwseFundamentalAdapter 纯解析逻辑离线测试（不联网）。"""

import datetime
from types import SimpleNamespace

import pytest
import requests

import data_provider.twse_fundamental_adapter as adapter_mod
from data_provider.twse_fundamental_adapter import (
    TwseFundamentalAdapter,
    _bare_code,
    _index_revenue_rows,
    _index_tpex_rows,
    _index_twse_rows,
    _pos_float,
    _snapshot_fresh,
)


@pytest.fixture(autouse=True)
def _no_local_valuation(monkeypatch):
    # get_valuation reads market.valuation first; keep these offline tests off the real DB.
    monkeypatch.setattr("market_data.market_repo.latest_valuation", lambda *a, **k: None)


def test_bare_code_strips_suffix():
    assert _bare_code("2330.TW") == "2330"
    assert _bare_code("6488.TWO") == "6488"
    assert _bare_code(" 2330 ") == "2330"
    assert _bare_code("aapl") == "AAPL"
    assert _bare_code("") == ""


def test_pos_float_rejects_nonpositive_and_garbage():
    assert _pos_float("31.46") == 31.46
    assert _pos_float("1,234.5") == 1234.5
    assert _pos_float("-") is None
    assert _pos_float("") is None
    assert _pos_float("N/A") is None
    assert _pos_float("0") is None       # 估值 0 无意义
    assert _pos_float("-5") is None      # 负数无意义
    assert _pos_float(None) is None
    assert _pos_float("abc") is None


def test_index_twse_rows():
    rows = [
        {"Code": "2330", "Name": "台積電", "PEratio": "31.46", "PBratio": "10.30", "DividendYield": "0.94"},
        {"Code": "9999", "PEratio": "-", "PBratio": "", "DividendYield": "0"},
        "garbage",
        {"Name": "无代码"},
    ]
    out = _index_twse_rows(rows)
    assert out["2330"] == {"pe_ratio": 31.46, "pb_ratio": 10.30, "dividend_yield": 0.94, "as_of": None}
    assert out["9999"] == {"pe_ratio": None, "pb_ratio": None, "dividend_yield": None, "as_of": None}
    assert "无代码" not in [k for k in out]


def test_index_tpex_rows():
    rows = [
        {
            "SecuritiesCompanyCode": "6488",
            "PriceEarningRatio": "57.74",
            "PriceBookRatio": "4.79",
            "YieldRatio": "0.82",
        }
    ]
    out = _index_tpex_rows(rows)
    assert out["6488"] == {"pe_ratio": 57.74, "pb_ratio": 4.79, "dividend_yield": 0.82, "as_of": None}


def test_index_revenue_rows_yoy_and_unit():
    rows = [
        {"公司代號": "2330", "資料年月": "11505",
         "營業收入-當月營收": "416975163", "營業收入-去年當月營收": "320543000"},
        {"公司代號": "1111", "資料年月": "11505",
         "營業收入-當月營收": "100", "營業收入-去年當月營收": "0"},   # 去年为0 -> yoy None
        {"公司代號": "2222", "資料年月": "11505",
         "營業收入-當月營收": "-", "營業收入-去年當月營收": "-"},      # 缺 -> 全 None
    ]
    out = _index_revenue_rows(rows)
    assert out["2330"]["monthly_revenue"] == 416975163 * 1000   # 千元 -> 元
    assert out["2330"]["monthly_revenue_yoy"] == round((416975163 - 320543000) / 320543000 * 100, 2)
    assert out["2330"]["revenue_month"] == "11505"
    assert out["1111"]["monthly_revenue_yoy"] is None and out["1111"]["monthly_revenue"] == 100 * 1000
    assert out["2222"]["monthly_revenue"] is None and out["2222"]["monthly_revenue_yoy"] is None


def test_indexers_tolerate_non_list():
    assert _index_twse_rows(None) == {}
    assert _index_tpex_rows({"not": "a list"}) == {}
    assert _index_revenue_rows(None) == {}


# ---- T12：月增／累計年增／民國月份轉換 ----

_REV_ROW = {
    "公司代號": "2330", "資料年月": "11509",
    "營業收入-當月營收": "335000000", "營業收入-去年當月營收": "216600000",
    "營業收入-上月比較增減(%)": "-0.57", "累計營業收入-前期比較增減(%)": "41.11",
}


def test_index_revenue_rows_keeps_negative_mom_and_cumulative_yoy():
    out = _index_revenue_rows([_REV_ROW])["2330"]
    assert out["monthly_revenue_mom"] == -0.57  # 負數不能被 _pos_float 吞成 None
    assert out["cumulative_revenue_yoy"] == 41.11
    assert out["revenue_month"] == "11509"
    assert out["revenue_month_iso"] == "2026-09"


def test_index_revenue_rows_missing_pct_columns_are_none():
    row = {k: v for k, v in _REV_ROW.items() if "比較增減" not in k}
    out = _index_revenue_rows([row, {**_REV_ROW, "公司代號": "2317",
                                       "營業收入-上月比較增減(%)": "-", "累計營業收入-前期比較增減(%)": ""}])
    assert out["2330"]["monthly_revenue_mom"] is None and out["2330"]["cumulative_revenue_yoy"] is None
    assert out["2317"]["monthly_revenue_mom"] is None and out["2317"]["cumulative_revenue_yoy"] is None


def test_revenue_month_iso_unparseable_is_none():
    for bad in (None, "", "abc", "11513", "1159"):
        row = {**_REV_ROW, "資料年月": bad if bad is not None else ""}
        assert _index_revenue_rows([row])["2330"]["revenue_month_iso"] is None, bad


def test_adapter_module_does_not_import_twse_fetcher_at_top_level():
    # twse_fetcher -> .base -> (頂層) twse_fundamental_adapter：頂層 import 會成環，必須 call-time import。
    import ast
    import data_provider.twse_fundamental_adapter as mod

    with open(mod.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert "twse_fetcher" not in (node.module or "")
            assert all(a.name != "twse_fetcher" for a in node.names)
        elif isinstance(node, ast.Import):
            assert all("twse_fetcher" not in a.name for a in node.names)


# ---- T13：估值 as_of、凍結快照拒收、上市上櫃分開快取、24h 回退上限 ----

_TODAY = datetime.date(2026, 10, 18)


@pytest.fixture(autouse=False)
def fixed_today(monkeypatch):
    monkeypatch.setattr(adapter_mod, "_today", lambda: _TODAY)


def _twse_row(code="2330", date="1151016", pe="31.46"):
    return {"Date": date, "Code": code, "PEratio": pe, "PBratio": "10.30", "DividendYield": "0.94"}


def _tpex_row(code="6488", date="1151016"):
    return {"Date": date, "SecuritiesCompanyCode": code, "PriceEarningRatio": "57.74",
            "PriceBookRatio": "4.79", "YieldRatio": "0.82"}


def test_rows_carry_as_of_from_roc_date():
    assert _index_twse_rows([_twse_row()])["2330"]["as_of"] == "2026-10-16"
    assert _index_tpex_rows([_tpex_row()])["6488"]["as_of"] == "2026-10-16"
    assert _index_twse_rows([_twse_row(date="")])["2330"]["as_of"] is None
    assert _index_twse_rows([_twse_row(date="abc")])["2330"]["as_of"] is None


def test_snapshot_fresh_rejects_frozen_snapshot(fixed_today):
    frozen = _index_twse_rows([_twse_row(date="1150730")])  # 2026-07-30，落後 80 天
    assert _snapshot_fresh(frozen) is False


def test_snapshot_fresh_rejects_snapshot_without_any_date(fixed_today):
    assert _snapshot_fresh(_index_twse_rows([_twse_row(date="")])) is False
    assert _snapshot_fresh({}) is False


def test_snapshot_fresh_accepts_d_minus_1_and_long_holiday_boundary(fixed_today):
    d_minus_1 = _index_twse_rows([_twse_row(date="1151016")])  # 落後 2 天（週五資料、週日取用）
    assert _snapshot_fresh(d_minus_1) is True
    on_limit = _TODAY - datetime.timedelta(days=adapter_mod._MAX_SNAPSHOT_AGE_DAYS)
    roc = f"{on_limit.year - 1911}{on_limit.month:02d}{on_limit.day:02d}"
    assert _snapshot_fresh(_index_twse_rows([_twse_row(date=roc)])) is True  # 春節長假（<=10 天）不拒收
    over = on_limit - datetime.timedelta(days=1)
    roc = f"{over.year - 1911}{over.month:02d}{over.day:02d}"
    assert _snapshot_fresh(_index_twse_rows([_twse_row(date=roc)])) is False


def test_snapshot_fresh_judges_by_newest_row_not_single_stale_row(fixed_today):
    # 整包判斷：一列日期異常舊不牽連整包；只有「最新的一列」都太舊才拒收。
    idx = _index_twse_rows([_twse_row("2330", "1151016"), _twse_row("1101", "1150101")])
    assert _snapshot_fresh(idx) is True


class _Resp:
    def __init__(self, payload=None, fail=False):
        self._payload, self._fail = payload, fail

    def raise_for_status(self):
        if self._fail:
            raise requests.HTTPError("boom")

    def json(self):
        return self._payload


class _FakeSession:
    """依 URL 回應並計數；``fail`` 內的 URL 丟 HTTPError。"""

    def __init__(self, payloads, fail=()):
        self.payloads, self.fail, self.calls = payloads, set(fail), []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return _Resp(self.payloads.get(url), fail=url in self.fail)


def _adapter(session):
    a = TwseFundamentalAdapter()
    a._session = session
    return a


def _payloads(twse_date="1151016", tpex_date="1151016"):
    return {
        adapter_mod._TWSE_BWIBBU_URL: [_twse_row(date=twse_date)],
        adapter_mod._TPEX_PERATIO_URL: [_tpex_row(date=tpex_date)],
    }


def test_get_valuation_returns_as_of_for_both_exchanges(fixed_today):
    a = _adapter(_FakeSession(_payloads()))
    assert a.get_valuation("2330.TW")["as_of"] == "2026-10-16"
    assert a.get_valuation("6488.TWO") == {
        "pe_ratio": 57.74, "pb_ratio": 4.79, "dividend_yield": 0.82, "as_of": "2026-10-16"}


def test_get_valuation_frozen_snapshot_returns_empty(fixed_today):
    a = _adapter(_FakeSession(_payloads(twse_date="1150730", tpex_date="1150730")))
    assert a.get_valuation("2330.TW") == {}
    assert a.get_valuation("6488.TWO") == {}


def test_frozen_twse_does_not_poison_fresh_tpex(fixed_today):
    a = _adapter(_FakeSession(_payloads(twse_date="1150730")))
    assert a.get_valuation("2330.TW") == {}
    assert a.get_valuation("6488.TWO")["as_of"] == "2026-10-16"


def test_twse_failure_is_retried_next_call_while_tpex_stays_cached(fixed_today):
    session = _FakeSession(_payloads(), fail={adapter_mod._TWSE_BWIBBU_URL})
    a = _adapter(session)
    assert a.get_valuation("6488.TWO")["as_of"] == "2026-10-16"
    assert a.get_valuation("6488.TWO")["as_of"] == "2026-10-16"
    twse_calls = session.calls.count(adapter_mod._TWSE_BWIBBU_URL)
    tpex_calls = session.calls.count(adapter_mod._TPEX_PERATIO_URL)
    assert twse_calls == 2      # 失敗不進快取，每次都重打上市
    assert tpex_calls == 1      # 上櫃成功的那份照常快取，不被上市失敗連坐
    # 上市恢復後下一次呼叫就拿得到，且不重打上櫃。
    session.fail.clear()
    assert a.get_valuation("2330.TW")["as_of"] == "2026-10-16"
    assert session.calls.count(adapter_mod._TWSE_BWIBBU_URL) == 3
    assert session.calls.count(adapter_mod._TPEX_PERATIO_URL) == 1


def test_tpex_failure_does_not_clear_twse_cache(fixed_today):
    session = _FakeSession(_payloads(), fail={adapter_mod._TPEX_PERATIO_URL})
    a = _adapter(session)
    assert a.get_valuation("2330.TW")["as_of"] == "2026-10-16"
    assert a.get_valuation("6488.TWO") == {}
    assert a.get_valuation("2330.TW")["as_of"] == "2026-10-16"
    assert session.calls.count(adapter_mod._TWSE_BWIBBU_URL) == 1


def _clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(adapter_mod, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def test_stale_cache_fallback_is_capped_at_24h(monkeypatch, fixed_today):
    now = _clock(monkeypatch)
    session = _FakeSession(_payloads())
    a = _adapter(session)
    assert a.get_valuation("2330.TW")["pe_ratio"] == 31.46
    session.fail.add(adapter_mod._TWSE_BWIBBU_URL)

    now[0] += adapter_mod._CACHE_TTL_SECONDS + 1            # TTL 已過、重抓失敗 -> 回退舊快取
    assert a.get_valuation("2330.TW")["pe_ratio"] == 31.46
    now[0] = 1000.0 + 24 * 3600 - 10                         # 寫死 24h：不跟著被測常數走；仍 < 24h
    assert a.get_valuation("2330.TW")["pe_ratio"] == 31.46
    now[0] = 1000.0 + 24 * 3600 + 10                         # 超過 24h -> 不再回退
    assert a.get_valuation("2330.TW") == {}


def test_frozen_refresh_falls_back_to_cache_only_within_24h(monkeypatch, fixed_today):
    now = _clock(monkeypatch)
    payloads = _payloads()
    a = _adapter(_FakeSession(payloads))
    assert a.get_valuation("2330.TW")["as_of"] == "2026-10-16"
    payloads[adapter_mod._TWSE_BWIBBU_URL] = [_twse_row(date="1150730")]   # 端點之後凍結
    now[0] += adapter_mod._CACHE_TTL_SECONDS + 1
    assert a.get_valuation("2330.TW")["as_of"] == "2026-10-16"             # 凍結快照不覆蓋好快取
    now[0] = 1000.0 + 24 * 3600 + 10
    assert a.get_valuation("2330.TW") == {}


def test_adapter_has_no_own_roc_parser():
    import inspect

    src = inspect.getsource(adapter_mod)
    assert "1911" not in src  # 民國轉西元只能走 twse_fetcher._roc_date，不自寫第三份
