# -*- coding: utf-8 -*-
"""新聞抓取窗口、來源路由、事件查詢與全文的守門測試（依 2026-11-01 實測評測）。"""

import logging
import sys
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

if "newspaper" not in sys.modules:
    sys.modules["newspaper"] = MagicMock()

from src.core.trading_calendar import is_market_open, recent_sessions_start  # noqa: E402
from src.search_service import (  # noqa: E402
    DeepSeekSearchProvider,
    MopsAnnouncementProvider,
    SearchResponse,
    SearchResult,
    SearchService,
    TavilySearchProvider,
    YFinanceNewsProvider,
    clean_page_navigation,
)
from src.services.event_gap import detect_event_gap, event_gap_context  # noqa: E402
from src.services.news_event_signals import resolve_news_event_signals  # noqa: E402

TODAY = date.today()


def _item(title, published, url=None, snippet="Intel INTC 台積電 2330 earnings 營收 目標價"):
    return SearchResult(title=title, snippet=snippet, url=url or f"https://news.example.com/{title}",
                        source="news.example.com",
                        published_date=published.isoformat() if isinstance(published, date) else published)


def _resp(name, items=()):
    return SearchResponse(query="q", results=list(items), provider=name)


class _Provider:
    """通過 isinstance 路由判斷的假來源，記下每次呼叫。"""

    def __init__(self, cls, name, handler=None):
        self.__class__ = type("Fake" + name, (_Provider, cls), {"search": _Provider.search, "name": name,
                                                                "is_available": True})
        self.calls = []
        self.handler = handler or (lambda query, kwargs: [_item(
            f"Intel INTC {name}" if "Intel" in query else f"台積電 2330 {name}", TODAY)])
        self.provider_name = name

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return _resp(self.provider_name, self.handler(query, kwargs))


def _service(*providers, mops=None, yf=None):
    service = SearchService(searxng_public_instances_enabled=False)
    service._providers = list(providers)
    service._mops_provider = mops
    service._yfinance_news_provider = yf
    return service


def _run(service, code="INTC", name="Intel", max_searches=5, **kwargs):
    # 窗口由市場當地日推算；美股在台北清晨會比本機早一天，要釘住。
    with patch("src.search_service.time.sleep"), patch.object(SearchService, "_attach_full_text"), \
            patch("src.search_service.get_market_now", return_value=datetime.combine(TODAY, datetime.min.time())):
        return service.search_comprehensive_intel(code, name, max_searches=max_searches, **kwargs)


def _titles(response):
    return [item.title for item in response.results]


def _dated_items(*offsets):
    return [_item(f"Intel INTC earnings d{offset}", TODAY - timedelta(days=offset)) for offset in offsets]


def _earnings_titles(offsets, **kwargs):
    deepseek = _Provider(DeepSeekSearchProvider, "DeepSeek", lambda q, k: _dated_items(*offsets))
    return _titles(_run(_service(deepseek), **kwargs)["earnings"])


# 1. earnings 窗口
def test_earnings_window_lower_bound_is_day_before_report():
    titles = _earnings_titles([11, 12], earnings_date=TODAY - timedelta(days=10))
    assert titles == ["Intel INTC earnings d11"]


def test_earnings_window_upper_bound_is_report_day_plus_seven():
    titles = _earnings_titles([2, 3], earnings_date=TODAY - timedelta(days=10))
    assert titles == ["Intel INTC earnings d3"]  # d3 = 財報日+7、d2 = 財報日+8


def test_earnings_window_falls_back_to_30_days():
    assert _titles(_run(_service(_Provider(DeepSeekSearchProvider, "DeepSeek",
                                           lambda q, k: _dated_items(29, 30, 180))))["earnings"]) == [
        "Intel INTC earnings d29"]


def test_anchored_earnings_request_uses_explicit_dates_not_180_days():
    tavily = _Provider(TavilySearchProvider, "Tavily", lambda q, k: [])
    _run(_service(tavily), earnings_date=TODAY - timedelta(days=20))
    window = [k["window"] for q, k in tavily.calls if "quarterly earnings" in q][0]
    assert window == (TODAY - timedelta(days=21), TODAY - timedelta(days=13))


def test_open_window_tolerates_one_day_ahead_but_not_two():
    ahead = [_item("Intel INTC tomorrow", TODAY + timedelta(days=1)), _item("Intel INTC later", TODAY + timedelta(days=2))]
    result = _run(_service(_Provider(DeepSeekSearchProvider, "DeepSeek", lambda q, k: ahead)))
    assert _titles(result["latest_news"]) == ["Intel INTC tomorrow"]


def test_earnings_older_than_30_days_is_not_anchored():
    titles = _earnings_titles([29, 41], earnings_date=TODAY - timedelta(days=40))
    assert titles == ["Intel INTC earnings d29"]


# 2. 交易日窗口
def _clean_sunday(market):
    """最近一個前三個平日都開市的週日；不寫死日曆日。"""
    day = TODAY - timedelta(days=(TODAY.weekday() + 1) % 7)
    while not all(is_market_open(market, day - timedelta(days=n)) for n in (2, 3, 4)):
        day -= timedelta(days=7)
    return day


@pytest.mark.parametrize("market", ["us", "tw"])
def test_sunday_window_reaches_wednesday(market):
    sunday = _clean_sunday(market)
    assert recent_sessions_start(market, sunday, 3) == sunday - timedelta(days=4)


def test_recent_sessions_counts_today_when_open():
    sunday = _clean_sunday("us")
    friday = sunday - timedelta(days=2)
    assert recent_sessions_start("us", friday, 1) == friday


def test_sunday_analysis_keeps_thursday_and_friday_articles_in_latest_and_risk():
    sunday = _clean_sunday("us")
    articles = lambda q, k: [  # noqa: E731
        _item("Intel INTC fri", sunday - timedelta(days=2)),
        _item("Intel INTC thu", sunday - timedelta(days=3)),
        _item("Intel INTC tue", sunday - timedelta(days=5)),
    ]
    deepseek = _Provider(DeepSeekSearchProvider, "DeepSeek", articles)
    now = datetime.combine(sunday, datetime.min.time())
    with patch("src.search_service.time.sleep"), patch("src.search_service.get_market_now", return_value=now):
        result = _service(deepseek).search_comprehensive_intel("INTC", "Intel", max_searches=5)
    for dim in ("latest_news", "risk_check"):
        assert set(_titles(result[dim])) == {"Intel INTC fri", "Intel INTC thu"}


def test_rank_prefers_post_event_articles():
    event = TODAY - timedelta(days=2)
    response = _resp("x", [_item("Intel INTC before", event - timedelta(days=1)), _item("Intel INTC after", event)])
    ranked = SearchService._rank_news_response(
        response, stock_code="INTC", stock_name="Intel", prefer_chinese=False, max_results=2, log_scope="t",
        post_event_date=event,
    )
    assert _titles(ranked) == ["Intel INTC after", "Intel INTC before"]


# 3. Tavily 摘要
def test_tavily_snippet_limit_and_navigation_cleanup():
    body = "Intel fell after guidance. " * 100
    content = "Skip to content\n\nLatest news\n\n" + body
    client = MagicMock()
    client.search.return_value = {"results": [{"title": "t", "url": "https://a.com/x", "content": content}]}
    with patch("tavily.TavilyClient", return_value=client):
        result = TavilySearchProvider(["k"]).search("q")
    snippet = result.results[0].snippet
    assert len(snippet) == 1500
    assert snippet.startswith("Intel fell")


def test_navigation_cleanup_removes_menus_but_keeps_article_lists():
    menu = "3. Magnificent 7\n   4. Private Markets\n   5. Futures & Derivatives\n"
    assert clean_page_navigation(menu + "Why Intel stock is trading lower") == "Why Intel stock is trading lower"
    article = "Key points:\n1. Revenue beat\n2. Guidance cut\nThe stock fell."
    assert clean_page_navigation(article) == article


def test_report_does_not_cut_long_snippets_to_150_chars():
    service = _service()
    long_snippet = "營收 " * 500
    report = service.format_intel_report(
        {"latest_news": _resp("x", [_item("t", TODAY, snippet=long_snippet)])}, "Intel")
    assert long_snippet.strip() in report


def test_report_includes_event_anchor_first():
    service = _service()
    report = service.format_intel_report(
        {"latest_news": _resp("x", [_item("later", TODAY)]), "event_anchor": _resp("x", [_item("first", TODAY)])},
        "Intel")
    assert report.index("first") < report.index("later")


# 4. 台股路由
def test_tw_event_dimensions_go_to_deepseek_without_tavily_news():
    tavily = _Provider(TavilySearchProvider, "Tavily")
    deepseek = _Provider(DeepSeekSearchProvider, "DeepSeek")
    # latest_news 不在改動範圍、仍走輪替；DeepSeek 排第一讓它也落在 DeepSeek，才能斷言 Tavily 完全沒被呼叫。
    result = _run(_service(deepseek, tavily), code="2330.TW", name="台積電")
    for dim in ("earnings", "risk_check", "announcements"):
        assert result[dim].provider == "DeepSeek"
    assert not tavily.calls


def test_tw_without_deepseek_uses_tavily_general_not_news():
    tavily = _Provider(TavilySearchProvider, "Tavily")
    _run(_service(tavily), code="2330.TW", name="台積電")
    event_calls = [k for q, k in tavily.calls if "最新" not in q]
    assert event_calls and not [k for k in event_calls if k.get("topic") == "news"]


def _mops(handler):
    provider = _Provider(MopsAnnouncementProvider, "MOPS", handler)
    return provider


def test_tw_announcements_use_mops_first_and_failure_falls_back():
    deepseek = _Provider(DeepSeekSearchProvider, "DeepSeek")
    mops = _mops(lambda q, k: [_item("台積電 2330 重訊", TODAY)])
    result = _run(_service(deepseek, mops=mops), code="2330.TW", name="台積電")
    assert result["announcements"].provider == "MOPS"
    assert mops.calls[0][1]["stock_code"] == "2330.TW"

    def boom(q, k):
        raise RuntimeError("mops down")

    result = _run(_service(deepseek, mops=_mops(boom)), code="2330.TW", name="台積電")
    assert result["announcements"].provider == "DeepSeek"


def test_mops_not_used_outside_tw():
    # A 股也有 announcements 面向；美股沒有這個面向，測不出代號判斷。
    mops = _mops(lambda q, k: [])
    _run(_service(_Provider(DeepSeekSearchProvider, "DeepSeek"), mops=mops), code="600519", name="贵州茅台")
    assert mops.calls == []


MOPS_HTML = """
<tr class='even'>
<td style='x'>&nbsp;3481</td><td style='x'>&nbsp;群創</td><td style='x'>&nbsp;115/10/28</td>
<td style='x'>&nbsp;16:40:48</td><td style='x'><pre><font size='3'>&nbsp;代子公司公告取得使用權資產</font></pre></td>
<td align='center'><input onclick="document.t05st01_fm.seq_no.value='1';"></td></tr>
<tr class='odd'><td>&nbsp;2330</td><td>&nbsp;台積電</td><td>&nbsp;115/10/28</td><td>&nbsp;09:00:00</td><td>別家</td></tr>
"""


def test_mops_parse_converts_roc_date_and_keeps_only_target_company():
    rows = MopsAnnouncementProvider.parse(MOPS_HTML, "3481")
    assert len(rows) == 1
    assert rows[0].published_date == "2026-10-28"
    assert rows[0].title == "群創 代子公司公告取得使用權資產"
    assert "seq_no=1" in rows[0].url


def test_mops_http_failure_returns_unsuccessful_response():
    with patch("src.search_service.requests.post", side_effect=OSError("boom")):
        result = MopsAnnouncementProvider().search("q", stock_code="3481.TW")
    assert result.success is False and result.results == []


def test_mops_queries_every_month_in_window():
    provider = MopsAnnouncementProvider()
    with patch.object(MopsAnnouncementProvider, "_fetch_month", return_value=[]) as fetch:
        provider.search("q", stock_code="3481.TW", window=(date(2026, 10, 29), date(2026, 11, 1)))
    assert [call.args[1:] for call in fetch.call_args_list] == [(2026, 10), (2026, 11)]


# 5. market_analysis
def test_market_analysis_is_seven_day_news_query():
    tavily = _Provider(TavilySearchProvider, "Tavily", lambda q, k: _dated_items(6, 7))
    deepseek = _Provider(DeepSeekSearchProvider, "DeepSeek", lambda q, k: [])
    result = _run(_service(deepseek, tavily))
    query, kwargs = [c for c in tavily.calls if "downgrade" in c[0]][0]
    assert kwargs["topic"] == "news"
    assert kwargs["window"][0] == TODAY - timedelta(days=6)
    assert _titles(result["market_analysis"]) == ["Intel INTC earnings d6"]


def test_market_analysis_news_drops_undated_data_pages():
    page = SearchResult("Intel INTC price target", "x", "https://simplywall.st/stocks/intc", "simplywall.st")
    deepseek = _Provider(DeepSeekSearchProvider, "DeepSeek", lambda q, k: [page])
    assert _run(_service(deepseek))["market_analysis"].results == []


def test_market_analysis_news_drops_video_even_when_dated():
    video = _item("Intel INTC price target", TODAY, url="https://www.youtube.com/watch?v=1")
    deepseek = _Provider(DeepSeekSearchProvider, "DeepSeek", lambda q, k: [video])
    assert _run(_service(deepseek))["market_analysis"].results == []


# 6. 事件錨定查詢
def _anchor_query(**kwargs):
    deepseek = _Provider(DeepSeekSearchProvider, "DeepSeek")
    tavily = _Provider(TavilySearchProvider, "Tavily")
    result = _run(_service(tavily, deepseek), **kwargs)
    return result, deepseek


def test_anchor_runs_within_seven_days_after_earnings_on_deepseek():
    result, deepseek = _anchor_query(earnings_date=TODAY - timedelta(days=7))
    assert result["event_anchor"].provider == "DeepSeek"
    assert deepseek.calls[0][0].startswith("why Intel INTC stock moved")


def test_anchor_skipped_eight_days_after_earnings():
    result, _ = _anchor_query(earnings_date=TODAY - timedelta(days=8))
    assert "event_anchor" not in result


def test_anchor_skipped_without_event():
    assert "event_anchor" not in _anchor_query()[0]


def test_anchor_runs_on_price_event_and_does_not_use_up_max_searches():
    event_day = TODAY - timedelta(days=1)
    result, _ = _anchor_query(price_event={"event_date": event_day.isoformat(), "change_pct": -28.0})
    assert "event_anchor" in result
    assert {"latest_news", "market_analysis", "risk_check", "earnings", "industry"} <= set(result)


def test_anchor_query_for_tw_uses_direction_and_local_date():
    deepseek = _Provider(DeepSeekSearchProvider, "DeepSeek")
    event_day = TODAY - timedelta(days=1)
    _run(_service(deepseek), code="3481.TW", name="群創",
         price_event={"event_date": event_day.isoformat(), "change_pct": -12.5})
    assert deepseek.calls[0][0] == f"群創 3481 股價 下跌 原因 {event_day.month}月{event_day.day}日"


def _open_week(market="us"):
    """最近一個週一到週五都開市的週一；不寫死日曆日。"""
    monday = TODAY - timedelta(days=TODAY.weekday() + 7)
    while not all(is_market_open(market, monday + timedelta(days=n)) for n in range(5)):
        monday -= timedelta(days=7)
    return monday


def _at(day, hour):
    return datetime.combine(day, datetime.min.time()).replace(hour=hour)


def _week_bars(monday, monday_change):
    return [{"date": (monday + timedelta(days=n)).isoformat(), "close": 100.0, "low": 95.0,
             "pct_chg": monday_change if n == 0 else 0.5} for n in range(5)]


_THRESHOLD_CONFIG = SimpleNamespace(event_gap_decision_enabled=False, event_gap_threshold_pct=12.0,
                                    event_gap_lookback_sessions=5)


def _signal(code, market, now, **kwargs):
    with patch("src.services.calendar_service.earnings_evidence", return_value={"date": None}):
        return resolve_news_event_signals(code, market, now, config=_THRESHOLD_CONFIG, **kwargs)


@pytest.mark.parametrize("change,expected", [(-12.0, True), (-11.9, False), (13.0, True)])
def test_price_signal_reuses_event_gap_threshold(change, expected):
    monday = _open_week()
    signals = _signal("INTC", "us", _at(monday + timedelta(days=4), 17), daily_bars=_week_bars(monday, change))
    assert bool(signals["price_event"]) is expected


def test_friday_and_sunday_see_the_same_event_from_the_same_bars():
    monday = _open_week()
    bars = _week_bars(monday, -20.0)
    friday = _signal("INTC", "us", _at(monday + timedelta(days=4), 17), daily_bars=bars)["price_event"]
    sunday = _signal("INTC", "us", _at(monday + timedelta(days=6), 10), daily_bars=bars)["price_event"]
    assert friday["event_date"] == monday.isoformat()
    assert sunday == friday


def _quote(change, provider_timestamp=None):
    return SimpleNamespace(change_pct=change, provider_timestamp=provider_timestamp)


def test_premarket_quote_without_bars_belongs_to_previous_session():
    next_monday = _open_week() + timedelta(days=7)
    if not is_market_open("us", next_monday):
        pytest.skip("next Monday is a holiday")
    event = _signal("INTC", "us", _at(next_monday, 8), realtime_quote=_quote(-20.0))["price_event"]
    assert event["event_date"] == (next_monday - timedelta(days=3)).isoformat()


def test_intraday_quote_without_bars_belongs_to_today():
    monday = _open_week()
    event = _signal("INTC", "us", _at(monday, 11), realtime_quote=_quote(-20.0))["price_event"]
    assert event["event_date"] == monday.isoformat()


def test_provider_timestamp_overrides_clock_for_quote_session():
    monday = _open_week()
    stamp = f"{monday - timedelta(days=3)}T16:00:00"
    event = _signal("INTC", "us", _at(monday, 11), realtime_quote=_quote(-20.0, stamp))["price_event"]
    assert event["event_date"] == (monday - timedelta(days=3)).isoformat()


@pytest.mark.parametrize("change,expected", [(-7.5, True), (-7.0, True), (-6.9, False)])
def test_tw_news_query_uses_seven_percent(change, expected):
    monday = _open_week("tw")
    signals = _signal("3481.TW", "tw", _at(monday + timedelta(days=4), 15), daily_bars=_week_bars(monday, change))
    assert bool(signals["price_event"]) is expected


def test_us_news_query_stays_on_shared_threshold():
    monday = _open_week()
    assert _signal("INTC", "us", _at(monday + timedelta(days=4), 17),
                   daily_bars=_week_bars(monday, -7.5))["price_event"] is None


def test_tw_decision_layer_threshold_unchanged():
    monday = _open_week("tw")
    friday = monday + timedelta(days=4)
    context = {"event_gap_daily_bars": _week_bars(monday, -7.5), "today": {"date": friday.isoformat()}}
    enabled = SimpleNamespace(event_gap_decision_enabled=True, event_gap_threshold_pct=12.0,
                              event_gap_lookback_sessions=5)
    assert event_gap_context("3481.TW", context, enabled) is None
    context["event_gap_daily_bars"] = _week_bars(monday, -12.5)
    assert event_gap_context("3481.TW", context, enabled)["threshold_pct"] == 12.0


def test_event_gap_switch_still_gates_only_the_decision_path():
    monday = _open_week()
    context = {"event_gap_daily_bars": _week_bars(monday, -20.0),
               "today": {"date": (monday + timedelta(days=4)).isoformat()}}
    assert event_gap_context("INTC", context, _THRESHOLD_CONFIG) is None
    assert detect_event_gap("INTC", context, _THRESHOLD_CONFIG)["change_pct"] == -20.0


def _signals_config():
    return SimpleNamespace(event_gap_threshold_pct=12.0, event_gap_lookback_sessions=5)


def test_earnings_signal_reads_item_202_only():
    good = (TODAY - timedelta(days=3)).isoformat()
    other = (TODAY - timedelta(days=1)).isoformat()
    context = {"us_evidence": {"sec_filings": {"recent_8k": [
        {"date": other, "items": "8.01"}, {"date": good, "items": "2.02,9.01"},
    ]}}}
    with patch("src.services.calendar_service.earnings_evidence", return_value={"date": None}):
        signals = resolve_news_event_signals("INTC", "us", _at(TODAY, 12), config=_signals_config(), fundamental_context=context)
    assert signals["earnings_date"] == TODAY - timedelta(days=3)


def test_earnings_signal_uses_calendar_only_on_the_day_itself():
    with patch("src.services.calendar_service.earnings_evidence", return_value={"date": TODAY.isoformat()}):
        assert resolve_news_event_signals("2330.TW", "tw", _at(TODAY, 12), config=_signals_config())["earnings_date"] == TODAY
    future = (TODAY + timedelta(days=1)).isoformat()
    with patch("src.services.calendar_service.earnings_evidence", return_value={"date": future}):
        assert resolve_news_event_signals("2330.TW", "tw", _at(TODAY, 12), config=_signals_config())["earnings_date"] is None


def test_signals_fail_open():
    with patch("src.services.calendar_service.earnings_evidence", side_effect=RuntimeError("db")):
        signals = resolve_news_event_signals("INTC", "us", _at(TODAY, 12), config=_signals_config())
    assert signals == {"earnings_date": None, "price_event": None}


# 7. 全文
def _extract_service(extract):
    tavily = TavilySearchProvider(["k"])
    tavily.extract = extract
    return _service(tavily)


def _articles(count=5):
    return {"event_anchor": _resp("Tavily", [
        _item(f"a{i}", TODAY, url=f"https://x.com/{i}", snippet="短摘要") for i in range(count)])}


def test_full_text_only_top_three_and_trimmed():
    calls = []

    def extract(urls):
        calls.append(urls)
        return {url: "Intel guidance " * 1000 for url in urls}

    results = _articles()
    _extract_service(extract)._attach_full_text(results, "Intel")
    assert calls == [[f"https://x.com/{i}" for i in range(3)]]
    snippets = [item.snippet for item in results["event_anchor"].results]
    assert all(2900 <= len(s) <= 3000 for s in snippets[:3])
    assert snippets[3:] == ["短摘要", "短摘要"]


def test_full_text_failure_keeps_summary():
    results = _articles(1)
    _extract_service(lambda urls: {})._attach_full_text(results, "Intel")
    assert results["event_anchor"].results[0].snippet == "短摘要"


def test_tavily_extract_exception_returns_empty():
    client = MagicMock()
    client.extract.side_effect = RuntimeError("boom")
    with patch("tavily.TavilyClient", return_value=client):
        assert TavilySearchProvider(["k"]).extract(["https://x.com"]) == {}


def test_full_text_requested_only_with_event():
    now = datetime.combine(TODAY, datetime.min.time())
    with patch("src.search_service.time.sleep"), patch("src.search_service.get_market_now", return_value=now), \
            patch.object(SearchService, "_attach_full_text") as attach:
        service = _service(_Provider(DeepSeekSearchProvider, "DeepSeek"))
        service.search_comprehensive_intel("INTC", "Intel", max_searches=5)
        attach.assert_not_called()
        service.search_comprehensive_intel("INTC", "Intel", max_searches=5, earnings_date=TODAY)
        attach.assert_called_once()


# 8. DeepSeek 後處理
def test_deepseek_filter_for_us_drops_cjk_and_hangul_and_logs(caplog):
    response = _resp("DeepSeek", [
        _item("英特爾 暴跌", TODAY), _item("인텔 주가", TODAY), _item("Intel falls", TODAY)])
    with caplog.at_level(logging.INFO, logger="src.search_service"):
        kept = SearchService._filter_deepseek_noise(response, "INTC")
    assert _titles(kept) == ["Intel falls"]
    assert "dropped=2" in caplog.text


def test_deepseek_filter_for_tw_drops_forum_only():
    response = _resp("DeepSeek", [
        _item("友達法說失靈", TODAY, url="https://api.cmoney.tw/forum/article/1"),
        _item("2337 旺宏 - 股市爆料同學會", TODAY, url="https://other.example.com/a"),
        _item("群創 重挫", TODAY, url="https://www.cmoney.tw/notes/1"),
    ])
    assert _titles(SearchService._filter_deepseek_noise(response, "3481.TW")) == ["群創 重挫"]


def test_deepseek_filter_leaves_other_markets_alone():
    response = _resp("DeepSeek", [_item("贵州茅台", TODAY)])
    assert _titles(SearchService._filter_deepseek_noise(response, "600519")) == ["贵州茅台"]


def test_filter_only_applies_to_deepseek_results():
    cjk = lambda q, k: [_item("英特爾 INTC Intel", TODAY)]  # noqa: E731
    assert _titles(_run(_service(_Provider(TavilySearchProvider, "Tavily", cjk)))["latest_news"])
    assert not _run(_service(_Provider(DeepSeekSearchProvider, "DeepSeek", cjk)))["latest_news"].results


# 9. yf.Search 備援
def test_yfinance_called_only_when_primary_empty():
    yf = _Provider(YFinanceNewsProvider, "yfinance")
    result = _run(_service(_Provider(DeepSeekSearchProvider, "DeepSeek", lambda q, k: []), yf=yf))
    assert result["latest_news"].provider == "yfinance"
    assert len(yf.calls) == 1  # 只補 latest_news

    yf = _Provider(YFinanceNewsProvider, "yfinance")
    _run(_service(_Provider(DeepSeekSearchProvider, "DeepSeek"), yf=yf))
    assert yf.calls == []


def test_yfinance_not_used_for_tw():
    yf = _Provider(YFinanceNewsProvider, "yfinance")
    _run(_service(_Provider(DeepSeekSearchProvider, "DeepSeek", lambda q, k: []), yf=yf), code="2330.TW", name="台積電")
    assert yf.calls == []


def test_yfinance_provider_parses_search_not_ticker_news():
    fake = MagicMock()
    published = int(datetime.now().timestamp())
    fake.Search.return_value.news = [
        {"title": "Intel falls", "link": "https://y.com/a", "publisher": "Reuters", "providerPublishTime": published}]
    with patch.dict(sys.modules, {"yfinance": fake}):
        result = YFinanceNewsProvider().search("q", stock_code="INTC")
    assert result.results[0].title == "Intel falls" and result.results[0].published_date
    fake.Search.assert_called_once()
    fake.Ticker.assert_not_called()


def test_yfinance_failure_is_unsuccessful_not_raised():
    fake = MagicMock()
    fake.Search.side_effect = RuntimeError("429")
    with patch.dict(sys.modules, {"yfinance": fake}):
        assert YFinanceNewsProvider().search("q", stock_code="INTC").success is False


def test_public_sources_off_by_default():
    service = SearchService(searxng_public_instances_enabled=False)
    assert service._mops_provider is None and service._yfinance_news_provider is None


# DeepSeek／Tavily 請求邊界
def test_deepseek_window_becomes_open_interval_bounds():
    provider = DeepSeekSearchProvider(["k"])
    with patch.object(provider, "_request_search", return_value={"results": []}) as request:
        provider.search("q", window=(date(2026, 10, 28), date(2026, 11, 1)))
    assert request.call_args.args[0] == "q after:2026-10-27 before:2026-11-02"


def test_tavily_window_uses_dates_and_never_advanced():
    client = MagicMock()
    client.search.return_value = {"results": []}
    with patch("tavily.TavilyClient", return_value=client):
        TavilySearchProvider(["k"]).search("q", window=(date(2026, 10, 28), date(2026, 11, 1)), topic="news")
    kwargs = client.search.call_args.kwargs
    assert kwargs["start_date"] == "2026-10-28" and kwargs["end_date"] == "2026-11-01"
    assert "days" not in kwargs
    assert kwargs["search_depth"] == "basic"
