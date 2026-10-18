# -*- coding: utf-8 -*-
"""TwseFundamentalAdapter 纯解析逻辑离线测试（不联网）。"""

from data_provider.twse_fundamental_adapter import (
    _bare_code,
    _index_revenue_rows,
    _index_tpex_rows,
    _index_twse_rows,
    _pos_float,
)


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
    assert out["2330"] == {"pe_ratio": 31.46, "pb_ratio": 10.30, "dividend_yield": 0.94}
    assert out["9999"] == {"pe_ratio": None, "pb_ratio": None, "dividend_yield": None}
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
    assert out["6488"] == {"pe_ratio": 57.74, "pb_ratio": 4.79, "dividend_yield": 0.82}


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
