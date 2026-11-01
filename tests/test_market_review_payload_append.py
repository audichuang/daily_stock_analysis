# -*- coding: utf-8 -*-
"""B07／B18：大盤複盤 payload 追加欄位、摘要取句與預設市場端點。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from market_data import sector_rank  # noqa: E402
from src.core.market_review import _summarize_market_review  # noqa: E402
from src.market_analyzer import (  # noqa: E402
    MarketAnalyzer,
    MarketIndex,
    MarketOverview,
    _extract_next_day_plan,
)


def _analyzer(region: str = "tw", language: str = "zh-TW") -> MarketAnalyzer:
    with patch(
        "src.market_analyzer.get_config",
        return_value=SimpleNamespace(report_language=language),
    ), patch("src.market_analyzer.DataFetcherManager"):
        return MarketAnalyzer(region=region)


# --- _summarize_market_review ------------------------------------------------


def test_summary_prefers_blockquote_under_title() -> None:
    report = "## 2026-10-30 大盤複盤\n\n> **量縮整理**，明日看 MA20。\n\n### 一、盤面總覽\n內容"
    assert _summarize_market_review(report, "zh-TW") == "量縮整理，明日看 MA20。"


def test_summary_skips_region_metadata_line() -> None:
    report = "[dsa-market-region]: # (tw)\n\n## 標題\n\n> 一句話\n"
    assert _summarize_market_review(report, "zh-TW") == "一句話"


def test_summary_ignores_blockquote_inside_sections() -> None:
    # 小節內的引用是系統註記（例如統計場次不符），不是結論；退回舊行為取標題。
    report = "## 標題\n\n### 一、盤面總覽\n> 家數資料不得推論\n"
    assert _summarize_market_review(report, "zh-TW") == "標題"


def test_summary_without_quote_keeps_first_line() -> None:
    assert _summarize_market_review("## 標題\n\n內文第一段", "zh-TW") == "標題"


# --- next_day_plan -----------------------------------------------------------


def test_plan_is_extracted_and_removed_from_markdown() -> None:
    report = (
        "## 標題\n\n正文\n\n```dsa-next-day-plan\n"
        '{"stance": "defensive", "summary": "看量", "focus": ["半導體"], "risks": [],'
        ' "key_levels": [{"label": "MA20", "price": 27000.5}]}\n```\n'
    )
    cleaned, plan = _extract_next_day_plan(report)
    assert "dsa-next-day-plan" not in cleaned
    assert cleaned.endswith("正文")
    assert plan["stance"] == "defensive"
    assert plan["key_levels"] == [{"label": "MA20", "price": 27000.5}]


def test_broken_plan_json_is_dropped_but_block_never_leaks() -> None:
    cleaned, plan = _extract_next_day_plan("正文\n```dsa-next-day-plan\n{not json\n```")
    assert plan is None
    assert "dsa-next-day-plan" not in cleaned


def test_truncated_plan_block_never_leaks() -> None:
    cleaned, plan = _extract_next_day_plan('正文\n```dsa-next-day-plan\n{"summary": "被截')
    assert cleaned == "正文"
    assert plan is None


def test_plan_rejects_bad_types() -> None:
    _, plan = _extract_next_day_plan(
        '```dsa-next-day-plan\n{"stance": "yolo", "summary": "x",'
        ' "key_levels": [{"label": "a", "price": true}, {"label": "b", "price": "1"}]}\n```'
    )
    assert plan["stance"] is None
    assert plan["key_levels"] == []


def test_report_without_plan_is_untouched() -> None:
    assert _extract_next_day_plan("## 標題\n正文") == ("## 標題\n正文", None)


def test_payload_only_carries_keys_with_readings() -> None:
    analyzer = _analyzer()
    empty = analyzer.build_market_review_payload(MarketOverview(date="2026-10-30"), [], "## t")
    for key in ("next_day_plan", "index_trends", "sector_rank"):
        assert key not in empty

    overview = MarketOverview(
        date="2026-10-30",
        index_trends={"TWII": {"as_of": "2026-10-30", "series": []}},
        sector_rank={"items": [{"name": "半導體業", "change_pct": 1.0}]},
        next_day_plan={"summary": "看量"},
    )
    payload = analyzer.build_market_review_payload(overview, [], "## t")
    assert payload["next_day_plan"] == {"summary": "看量"}
    assert payload["index_trends"]["TWII"]["as_of"] == "2026-10-30"
    assert payload["sector_rank"]["items"][0]["name"] == "半導體業"


# --- 燈號理由語言 -------------------------------------------------------------


def test_zh_tw_market_light_reasons_are_traditional() -> None:
    overview = MarketOverview(
        date="2026-10-30",
        indices=[MarketIndex(code="TWII", name="加權", current=1.0, change_pct=1.0)],
        up_count=700,
        down_count=300,
        limit_up_count=5,
    )
    text = "".join(_analyzer(language="zh-TW")._build_market_light_reasons_zh(overview, 60))
    assert "上漲家數占比" in text
    assert "主要指數平均漲跌幅" in text
    for simplified in ("上涨", "家数", "赚钱", "涨跌"):
        assert simplified not in text


def test_zh_cn_market_light_reasons_stay_simplified() -> None:
    overview = MarketOverview(date="2026-10-30", up_count=700, down_count=300)
    text = "".join(_analyzer(language="zh")._build_market_light_reasons_zh(overview, 60))
    assert "上涨家数占比" in text


# --- sector_rank -------------------------------------------------------------


def test_index_trend_series_and_ma_distance() -> None:
    rows = [{"date": f"2026-01-{i:02d}", "close": 100.0} for i in range(1, 21)]
    rows.append({"date": "2026-02-01", "close": 110.0})
    trend = sector_rank.compute_index_trend(rows)
    assert len(trend["series"]) == 20
    assert trend["as_of"] == "2026-02-01"
    assert trend["ma20"] == 100.5
    assert trend["distance_ma20_pct"] == round((110 / 100.5 - 1) * 100, 2)
    # 只有 21 場：MA60 沒有讀數，不拿短窗口冒充
    assert trend["ma60"] is None
    assert trend["distance_ma60_pct"] is None


def test_index_trend_skips_non_finite_rows() -> None:
    assert sector_rank.compute_index_trend([{"date": "2026-01-01", "close": float("nan")}]) is None


def test_tw_sector_rank_weights_by_turnover_and_filters() -> None:
    rows = [
        {"industry": "24", "close": 110, "prev_close": 100, "turnover": 300},
        {"industry": "24", "close": 100, "prev_close": 100, "turnover": 100},
        {"industry": "24", "close": 100, "prev_close": 100, "turnover": 100},
        # 查無代碼、樣本不足、超過漲跌停的都不算
        {"industry": "99", "close": 110, "prev_close": 100, "turnover": 100},
        {"industry": "17", "close": 101, "prev_close": 100, "turnover": 100},
        {"industry": "24", "close": 150, "prev_close": 100, "turnover": 9999},
    ]
    assert sector_rank.rank_tw_sectors(rows) == [
        {"name": "半導體業", "change_pct": 6.0, "turnover": 500.0, "stock_count": 3}
    ]


def test_us_sector_rank_only_accepts_same_session() -> None:
    def closes(code: str) -> list:
        if code == "XLK":
            return [{"date": "2026-10-29", "close": 100}, {"date": "2026-10-30", "close": 102}]
        if code == "XLF":
            return [{"date": "2026-10-28", "close": 100}, {"date": "2026-10-29", "close": 99}]
        raise RuntimeError("down")

    result = sector_rank.rank_us_sector_etfs("2026-10-30", closes)
    assert [item["code"] for item in result["items"]] == ["XLK"]
    assert result["items"][0]["change_pct"] == 2.0


def test_us_sector_rank_none_when_no_readings() -> None:
    assert sector_rank.rank_us_sector_etfs("2026-10-30", lambda code: []) is None


def test_attach_trends_is_fail_open_for_us() -> None:
    analyzer = _analyzer(region="us")
    analyzer.data_manager.get_daily_data.side_effect = RuntimeError("boom")
    overview = MarketOverview(date="2026-10-30", indices=[MarketIndex(code="SPX", name="SPX")])
    analyzer._attach_review_trends(overview)
    assert overview.index_trends == {}
    assert overview.sector_rank is None


def test_attach_trends_fills_us_index_trend() -> None:
    analyzer = _analyzer(region="us")
    df = pd.DataFrame({"date": ["2026-10-29", "2026-10-30"], "close": [100.0, 101.0]})
    analyzer.data_manager.get_daily_data.return_value = (df, "yfinance")
    overview = MarketOverview(date="2026-10-30", indices=[MarketIndex(code="SPX", name="SPX")])
    analyzer._attach_review_trends(overview)
    assert overview.index_trends["SPX"]["as_of"] == "2026-10-30"
    assert overview.sector_rank["source"] == "yfinance"
    assert len(overview.sector_rank["items"]) == len(sector_rank.US_SECTOR_ETFS)


def test_attach_trends_skips_other_markets() -> None:
    analyzer = _analyzer(region="cn", language="zh")
    overview = MarketOverview(date="2026-10-30", indices=[MarketIndex(code="sh000001", name="上證")])
    analyzer._attach_review_trends(overview)
    analyzer.data_manager.get_daily_data.assert_not_called()


# --- B18 -----------------------------------------------------------------------


def test_default_region_endpoint_keeps_configured_order() -> None:
    from api.v1.endpoints.analysis import get_market_review_default_region

    result = get_market_review_default_region(config=SimpleNamespace(market_review_region="tw,us"))
    assert result.default_region == "tw,us"
    assert result.regions == ["tw", "us"]


def test_default_region_endpoint_falls_back_like_trigger() -> None:
    from api.v1.endpoints.analysis import get_market_review_default_region

    result = get_market_review_default_region(config=SimpleNamespace(market_review_region="nope"))
    assert result.default_region == "cn"
    assert result.regions == ["cn"]
