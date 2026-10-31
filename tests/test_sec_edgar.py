"""SEC／FINRA fixture、預算、來源優先序與關閉相容性。"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
from xml.etree import ElementTree

import pytest

from tests.litellm_stub import ensure_litellm_stub
ensure_litellm_stub()
from data_provider.sec_edgar import SecEdgarClient, earnings_excerpt, parse_form4
from data_provider.us_evidence import format_us_evidence, sec_news_evidence_present
from tests.test_event_gap_decision import _analyzer, _context, _finish
from tests.test_us_data_evidence import _manager

FIXTURES = Path(__file__).parent / "fixtures"


def _json(name):
    return json.loads((FIXTURES / name).read_text())


def _submissions(code="intc", now=None):
    data = _json(f"sec_submissions_{code}.json")
    now = now or date.today()
    # 實際回應縮本的日期整體平移；保留跨申報間的相對間距。
    recent = data["filings"]["recent"]
    offset = now - date(2026, 10, 31)
    recent["filingDate"] = [(date.fromisoformat(d) + offset).isoformat() for d in recent["filingDate"]]
    return data


def _xml(code="intc", now=None):
    xml = (FIXTURES / f"sec_form4_{code}.xml").read_text()
    root = ElementTree.fromstring(xml)
    for node in root.findall(".//transactionDate/value"):
        xml = xml.replace(node.text, ((now or date.today()) - timedelta(days=2)).isoformat())
    return xml


def _fixture_client(monkeypatch, code="intc"):
    client = SecEdgarClient("fixture contact", request_timeout=30)
    calls = []

    def get_json(url, **kwargs):
        calls.append(url)
        if "company_tickers" in url:
            return _json("sec_company_tickers.json")
        if "submissions" in url:
            return _submissions(code)
        if url.endswith("index.json"):
            return _json(f"sec_index_{code}.json")
        if "finra" in url:
            return _json("finra_short_intc.json")
        raise AssertionError(url)

    monkeypatch.setattr(client, "_json", get_json)
    monkeypatch.setattr(client, "_text", lambda url, **kw: _xml(code) if url.endswith(".xml") else (FIXTURES / "sec_earnings_intc.htm").read_text())
    monkeypatch.setattr("data_provider.sec_edgar._TICKERS", {})
    return client, calls


@pytest.mark.parametrize("code", ["intc", "goog"])
def test_real_submission_shapes_earnings_and_form4(monkeypatch, code):
    client, _ = _fixture_client(monkeypatch, code)
    evidence = client.get_evidence(code.upper(), deadline=time.monotonic() + 60, now=date.today())
    sec = evidence["sec_filings"]
    assert sec["latest_10q_date"] == (date.today() - timedelta(days=1 if code == "intc" else 2)).isoformat()
    assert len(sec["recent_8k"]) == 1
    filing = sec["recent_8k"][0]
    assert filing["items"] == "2.02,9.01"
    assert filing["accepted_at"]
    assert "Forecasting fourth-quarter" in filing["excerpt"]
    assert "$15.0 billion to $16.0 billion" in filing["excerpt"]
    assert "$0.25" in filing["excerpt"]
    assert "<" not in filing["excerpt"]
    assert len(filing["excerpt"]) <= 6000
    assert sec_news_evidence_present({"us_evidence": evidence}, now=date.today())
    insider = evidence["insider_form4"]
    assert insider["complete"]
    assert insider["filings_read"] == 2
    assert insider["classified_count"] == 2
    assert insider["net_shares"] > 0 if code == "intc" else insider["net_shares"] < 0


def test_ticker_cache_and_share_class_alias(monkeypatch):
    client, calls = _fixture_client(monkeypatch)
    deadline = time.monotonic() + 60
    assert client._cik("GOOG", deadline=deadline) == client._cik("GOOGL", deadline=deadline)
    assert client._cik("BRK.B", deadline=deadline) == "1067983"
    assert client._cik("NOTATICKER", deadline=deadline) is None
    assert sum("company_tickers" in url for url in calls) == 1


def test_attachment_discovery_uses_content_not_fixed_filename(monkeypatch):
    client = SecEdgarClient("fixture")
    monkeypatch.setattr(client, "_json", lambda *a, **kw: {"directory": {"item": [
        {"name": "cover.htm"}, {"name": "R1.htm"}, {"name": "a-index.html"}, {"name": "other.htm"}, {"name": "unpredictable.htm"}]}})
    calls = []
    def text(url, **kwargs):
        calls.append(url)
        return "<html>Cover only</html>" if url.endswith("other.htm") else (FIXTURES / "sec_earnings_intc.htm").read_text()
    monkeypatch.setattr(client, "_text", text)
    result = client._earnings("https://www.sec.gov/Archives/", "cover.htm", deadline=time.monotonic() + 60)
    assert result["excerpt_url"].endswith("unpredictable.htm")
    assert len(calls) == 2
    long_html = "<p>Financial results revenue earnings</p>" + "<p>old boilerplate</p>" * 1500 + "<p>Forecast revenue $16 billion EPS $0.25</p>"
    excerpt = earnings_excerpt(long_html, limit=300)
    assert excerpt.startswith("old boilerplate\nForecast revenue")
    assert len(excerpt) <= 300
    assert earnings_excerpt("<h1>8-K</h1><p>SEC filing cover</p>") == ""


def test_form4_only_ps_non_derivative_and_window():
    now = date.today()
    root = ElementTree.fromstring(_xml(now=now))
    transaction = root.find(".//nonDerivativeTransaction")
    table = root.find("nonDerivativeTable")
    table.clear()
    for code, days in [("P", 1), ("S", 90), ("A", 1), ("M", 1), ("F", 1), ("G", 1), ("P", 91), ("S", -1)]:
        node = deepcopy(transaction)
        node.find("transactionCoding/transactionCode").text = code
        node.find("transactionDate/value").text = (now - timedelta(days=days)).isoformat()
        node.find("transactionAmounts/transactionShares/value").text = "100"
        table.append(node)
    node = deepcopy(transaction); node.tag = "derivativeTransaction"
    root.append(node)
    result = parse_form4(ElementTree.tostring(root, encoding="unicode"), now=now)
    assert result == {"buy_shares": 100, "sell_shares": 100, "classified_count": 2, "excluded_count": 5}
    with pytest.raises(ValueError):
        parse_form4('<!DOCTYPE x [<!ENTITY x "abc">]><ownershipDocument/>', now=now)


def test_partial_form4_and_attachment_failure_keep_metadata(monkeypatch):
    client, _ = _fixture_client(monkeypatch)
    xml_calls = []
    def text(url, **kwargs):
        if not url.endswith(".xml") or xml_calls:
            raise TimeoutError("fixture server slow")
        xml_calls.append(url)
        return _xml()
    monkeypatch.setattr(client, "_text", text)
    result = client.sec_evidence("INTC", deadline=time.monotonic() + 60, now=date.today())
    assert result["sec_filings"]["recent_8k"][0]["items"] == "2.02,9.01"
    assert "excerpt" not in result["sec_filings"]["recent_8k"][0]
    assert result["insider_form4"]["filings_read"] == 1
    assert not result["insider_form4"]["complete"]
    assert sec_news_evidence_present({"us_evidence": result}, now=date.today())


def test_finra_unsorted_latest_non_future_and_missing_values(monkeypatch):
    client = SecEdgarClient("fixture")
    today = date.today()
    rows = _json("finra_short_intc.json")
    for i, row in enumerate(rows):
        row["settlementDate"] = (today - timedelta(days=i+1)).isoformat()
    rows = rows[::-1] + [dict(rows[0], settlementDate=(today + timedelta(days=1)).isoformat())]
    call = Mock(return_value=rows)
    monkeypatch.setattr(client, "_json", call)
    result = client.finra_short("INTC", deadline=time.monotonic() + 60, now=today)
    assert result == {"shares_short": 148504504, "days_to_cover": 1.54, "as_of": (today - timedelta(days=1)).isoformat()}
    payload = call.call_args.kwargs["payload"]
    assert "sortFields" not in payload
    assert payload["compareFilters"] == [{"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": "INTC"}]
    rows[-2]["daysToCoverQuantity"] = None
    assert "days_to_cover" not in client.finra_short("INTC", deadline=time.monotonic() + 60, now=today)


@pytest.mark.parametrize("failing", ["sec", "finra"])
def test_sources_fail_independently(monkeypatch, failing):
    client = SecEdgarClient("fixture")
    monkeypatch.setattr(client, "sec_evidence", Mock(side_effect=TimeoutError) if failing == "sec" else Mock(return_value={"sec_filings": {"latest_10q_date": "fixture"}}))
    monkeypatch.setattr(client, "finra_short", Mock(side_effect=TimeoutError) if failing == "finra" else Mock(return_value={"shares_short": 1}))
    result = client.get_evidence("INTC", deadline=time.monotonic() + 60)
    assert ("sec_filings" in result) is (failing != "sec")
    assert ("finra_short" in result) is (failing != "finra")


@pytest.mark.parametrize("ua,code", [("", "INTC"), ("fixture", "2330.TW"), ("fixture", "0700.HK")])
def test_disabled_and_non_us_never_request(monkeypatch, ua, code):
    client = SecEdgarClient(ua)
    request = Mock(side_effect=AssertionError("must not request"))
    monkeypatch.setattr(client, "_request", request)
    assert client.get_evidence(code, deadline=time.monotonic() + 60) == {}
    request.assert_not_called()


def test_expired_deadline_never_starts_http():
    client = SecEdgarClient("fixture")
    with pytest.raises(TimeoutError):
        client._request("https://data.sec.gov/", deadline=time.monotonic() - 1)


def test_request_headers_timeout_and_global_sec_rate(monkeypatch):
    # 僅 transport 邊界用 fake requests；其餘測試 mock 自家接縫。
    import data_provider.sec_edgar as module
    times = []
    def get(url, **kwargs):
        times.append(time.monotonic())
        assert kwargs["headers"]["User-Agent"] == "configured contact"
        assert 0 < kwargs["timeout"] <= .5
        return SimpleNamespace(raise_for_status=lambda: None)
    monkeypatch.setattr(module.requests, "get", get)
    monkeypatch.setattr(module, "_SEC_LAST_REQUEST", 0)
    for _ in range(3):
        SecEdgarClient("configured contact", request_timeout=.5)._request("https://data.sec.gov/", deadline=time.monotonic() + 60)
    assert all(b - a >= .10 for a, b in zip(times, times[1:]))


def test_prompt_official_precedence_and_field_fallback():
    context = {"us_evidence": {"short_interest": {"shares_short": 999, "days_to_cover": 99, "float_pct": 12, "as_of": "yahoo-date"},
                               "insider_90d": {"buy_shares": 888}, "insider_form4": {"buy_shares": 100, "complete": False},
                               "finra_short": {"shares_short": 123, "days_to_cover": 1.5, "as_of": "finra-date"},
                               "sec_filings": {"recent_8k": []}}}
    text = format_us_evidence(context)
    assert "SEC 官方申報，來源一手；新聞稿內容為公司自述" in text
    assert "999" not in text and "888" not in text and "99," not in text
    assert "finra-date" in text and '"buy_shares": 100' in text
    assert '"float_pct": 12' in text
    del context["us_evidence"]["finra_short"]["days_to_cover"]
    text = format_us_evidence(context)
    assert '"days_to_cover": 99' in text


@pytest.mark.parametrize("age,items,excerpt,expected", [
    (0, "2.02,9.01", "", True), (14, " 2.02 ,9.01", "", True), (15, "2.02", "", False),
    (-1, "2.02", "", False), (1, "9.01", "", False), (1, "", "real excerpt", True),
    (1, "", "  ", False), (1, "12.02", "", False)])
def test_sec_news_requires_recent_substance(age, items, excerpt, expected):
    context = {"us_evidence": {"sec_filings": {"recent_8k": [{"date": (date.today() - timedelta(days=age)).isoformat(), "items": items, "excerpt": excerpt}]}}}
    assert sec_news_evidence_present(context, now=date.today()) is expected


def test_unset_config_and_baseline_byte_for_byte(monkeypatch):
    from src.config import Config
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
    with patch("src.config.setup_env"), patch.object(Config, "_capture_bootstrap_runtime_env_overrides"):
        assert Config._load_from_env().sec_edgar_user_agent == ""
    baseline = _json("sec_disabled_baseline.json")
    context = _context(); context["fundamental_context"] = baseline["fundamental"]
    assert format_us_evidence(baseline["fundamental"]) == baseline["evidence_prompt"]
    for language, expected in baseline["prompts"].items():
        assert sha256(_analyzer()._format_prompt(context, "Test", report_language=language).encode()).hexdigest() == expected
    _, saved, _ = _finish(SimpleNamespace(report_language="zh-TW", event_gap_decision_enabled=True, event_gap_threshold_pct=12), context)
    # 本輪獨立新增事件收盤事實；舊 SEC 快照保留，先逐值驗證新增欄再比對其餘內容。
    assert saved["dashboard"]["event_gap"].pop("latest_close") == context["today"]["close"]
    assert saved == baseline["result"]
    from src.agent.executor import AgentExecutor
    executor = AgentExecutor.__new__(AgentExecutor)
    executor.skill_instructions = ""; executor.default_skill_policy = ""; executor.use_legacy_default_prompt = True
    executor.tool_registry = Mock(); executor.tool_registry.to_openai_tools.return_value = []; executor._run_loop = Mock()
    executor.run("Analyze", {"stock_code": "INTC", "us_evidence_prompt": baseline["evidence_prompt"]})
    assert executor._run_loop.call_args.args[0] == baseline["agent_messages"]


def test_manager_disabled_and_enabled_official_evidence(monkeypatch):
    manager = _manager(monkeypatch, stage=2)
    monkeypatch.setattr(manager._yfinance_fundamental_adapter, "get_us_activity_evidence", lambda *a: {})
    monkeypatch.setattr("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", lambda: False)
    call = Mock(return_value={"sec_filings": {"recent_8k": []}})
    monkeypatch.setattr(SecEdgarClient, "get_evidence", call)
    old = manager.get_fundamental_context("INTC")
    call.assert_not_called()
    config = __import__("src.config", fromlist=["get_config"]).get_config()
    config.sec_edgar_user_agent = "fixture contact"
    new = manager.get_fundamental_context("INTC")
    assert new["us_evidence"]["sec_filings"] == {"recent_8k": []}
    assert call.call_args.kwargs["deadline"] <= time.monotonic() + 2
    assert new["capital_flow"] == old["capital_flow"]
    assert new["coverage"] == old["coverage"]
    manager.close()


def test_manager_official_request_obeys_stage_budget(monkeypatch):
    from threading import Event
    manager = _manager(monkeypatch, stage=.1, fetch=.1)
    config = __import__("src.config", fromlist=["get_config"]).get_config()
    config.sec_edgar_user_agent = "fixture contact"
    release, done = Event(), Event()
    def blocked(*args, **kwargs):
        release.wait(30); done.set(); return {"sec_filings": {"late": True}}
    monkeypatch.setattr(SecEdgarClient, "get_evidence", blocked)
    monkeypatch.setattr(manager._yfinance_fundamental_adapter, "get_us_activity_evidence", Mock(side_effect=AssertionError("budget exhausted")))
    monkeypatch.setattr("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", lambda: False)
    start = time.monotonic()
    try:
        result = manager.get_fundamental_context("INTC")
        assert time.monotonic() - start < 2
        assert "sec_filings" not in result["us_evidence"]
        assert result["us_evidence"]["short_interest"]["shares_short"] == 123
    finally:
        release.set(); assert done.wait(30); manager.close()


def test_archived_submissions_and_failed_history_are_explicit(monkeypatch):
    client, _ = _fixture_client(monkeypatch)
    data = _submissions()
    recent = data["filings"]["recent"]
    form4_index = recent["form"].index("4")
    archived = {key: [values[form4_index]] for key, values in recent.items()}
    recent = {key: [value for i, value in enumerate(values) if recent["form"][i] != "4"] for key, values in recent.items()}
    data["filings"]["recent"] = recent
    data["filings"]["files"] = [{"name": "older.json", "filingTo": date.today().isoformat()}]
    original = client._json
    def get_json(url, **kwargs):
        if url.endswith("older.json"):
            return archived
        if "submissions" in url:
            return data
        return original(url, **kwargs)
    monkeypatch.setattr(client, "_json", get_json)
    result = client.sec_evidence("INTC", deadline=time.monotonic()+60, now=date.today())
    assert result["insider_form4"]["filings_read"] == 1
    assert result["insider_form4"]["complete"]
    def failed(url, **kwargs):
        if url.endswith("older.json"):
            raise TimeoutError("archive unavailable")
        return get_json(url, **kwargs)
    monkeypatch.setattr(client, "_json", failed)
    result = client.sec_evidence("INTC", deadline=time.monotonic()+60, now=date.today())
    assert "insider_form4" not in result
    assert result["sec_filings"]["recent_8k"]


@pytest.mark.parametrize("value", ["NaN", "-1", "Infinity", "not a number"])
def test_invalid_form4_shares_are_excluded(value):
    root = ElementTree.fromstring(_xml())
    root.find(".//transactionShares/value").text = value
    result = parse_form4(ElementTree.tostring(root, encoding="unicode"), now=date.today())
    assert result["classified_count"] == 0
    assert result["excluded_count"] == 1
    assert result["buy_shares"] == 0


def test_configured_user_agent_and_cache_switch(monkeypatch):
    from src.config import Config
    from src.core.config_registry import WEB_SETTINGS_HIDDEN_FROM_UI, build_schema_response
    import os
    assert "SEC_EDGAR_USER_AGENT" in WEB_SETTINGS_HIDDEN_FROM_UI
    assert "SEC_EDGAR_USER_AGENT" not in {
        field["key"] for category in build_schema_response()["categories"] for field in category["fields"]}
    with patch.dict(os.environ, {"SEC_EDGAR_USER_AGENT": "  configured contact  "}), \
            patch("src.config.setup_env"), patch.object(Config, "_capture_bootstrap_runtime_env_overrides"):
        assert Config._load_from_env().sec_edgar_user_agent == "configured contact"
    manager = _manager(monkeypatch)
    config = __import__("src.config", fromlist=["get_config"]).get_config()
    config.fundamental_cache_ttl_seconds = 60
    monkeypatch.setattr(manager._yfinance_fundamental_adapter, "get_us_activity_evidence", lambda *a: {})
    monkeypatch.setattr("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", lambda: False)
    monkeypatch.setattr(SecEdgarClient, "get_evidence", lambda *a, **kw: {"sec_filings": {"latest_10q_date": "fixture"}})
    # 快取可用的核心區塊；純資訊不參與 status／coverage。
    bundle = manager._yfinance_fundamental_adapter.get_fundamental_bundle
    monkeypatch.setattr(manager._yfinance_fundamental_adapter, "get_fundamental_bundle", lambda code: dict(bundle(code), growth={"revenue_yoy": 10}))
    before = manager.get_fundamental_context("INTC")
    config.sec_edgar_user_agent = "fixture"
    enabled = manager.get_fundamental_context("INTC")
    assert "sec_filings" in enabled["us_evidence"]
    config.sec_edgar_user_agent = ""
    after = manager.get_fundamental_context("INTC")
    assert after == before
    manager.close()
