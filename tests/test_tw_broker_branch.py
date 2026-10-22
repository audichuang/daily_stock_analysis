"""券商分點前 15 名（富邦 DJ）解析與 HHI。fixture 是 3324 雙鴻 2026-08-28 的原始 Big5 頁面。"""

import datetime as dt
from pathlib import Path

from data_provider.tw_broker_branch import hhi_top15, parse_branch_page

_DAY = dt.date(2026, 8, 28)
_HTML = (Path(__file__).parent / "fixtures" / "fubon_zco_3324_20260828.bin").read_bytes().decode(
    "big5", errors="replace")


def test_parses_both_sides_and_footer():
    out = parse_branch_page(_HTML, _DAY, _DAY)
    assert len(out["buy"]) == 15 and len(out["sell"]) == 15
    assert out["buy"][0] == {"branch": "台灣摩根士丹利", "buy": 543, "sell": 90, "net": 453, "share_pct": 7.0}
    assert out["sell"][0]["branch"] == "第一金-中山" and out["sell"][0]["net"] == 100
    assert (out["buy_total"], out["avg_buy_cost"]) == (2893, 1128.61)


def test_hhi_over_top15_buyers():
    # 與 botbook.cc 3324 報告的「買方 HHI 959」一致：對方同樣只用前 15 名買超分點
    assert hhi_top15(parse_branch_page(_HTML, _DAY, _DAY)["buy"]) == 959


def test_hhi_single_buyer_is_10000_and_empty_is_none():
    assert hhi_top15([{"net": 5}]) == 10000
    assert hhi_top15([]) is None


def test_rejects_page_for_a_different_range():
    assert parse_branch_page(_HTML, dt.date(2026, 8, 27), _DAY) is None


def test_multi_day_range_reads_start_from_getymd2():
    # 頁面 getYMD1 = 迄日、getYMD2 = 起日；單日 fixture 兩者相同，改寫成 8/24~8/28 區間
    html = _HTML.replace("getYMD2 = '2026/8/28'", "getYMD2 = '2026/8/24'")
    assert parse_branch_page(html, dt.date(2026, 8, 24), _DAY) is not None
    assert parse_branch_page(html, _DAY, dt.date(2026, 8, 24)) is None


def test_no_data_page_returns_none():
    # 查無資料頁：表頭之後只有一列「查無…」，沒有分點列
    empty = _HTML[:_HTML.index("買超券商")] + "<tr><td colspan=10>查無(3324)券商分點-進出明細</td></tr>"
    assert parse_branch_page(empty, _DAY, _DAY) is None
