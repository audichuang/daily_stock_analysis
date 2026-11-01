# -*- coding: utf-8 -*-
"""財報導讀契約：欄位 key 驗證、數字只能來自程式、快取不重打 LLM、失敗不影響數字。"""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.services import financial_commentary as fc  # noqa: E402
from src.storage import DatabaseManager, FinancialCommentaryRecord  # noqa: E402


def _payload(**overrides):
    base = {
        "stock_code": "2330.TW", "stock_name": "台積電", "status": "ok", "template": "general", "currency": "TWD",
        "source": {"id": "market.financial_statement"},
        "periods": [{"key": "2099Q1", "period_end": "2099-03-31"}, {"key": "2099Q2", "period_end": "2099-06-30"}],
        "metrics": [
            {"key": "revenue", "label": "營收", "kind": "amount", "definition": "d", "points": [
                {"period": "2099Q1", "value": 1.1e12, "yoy_pct": None, "qoq_pct": None, "yoy_pp": None, "qoq_pp": None},
                {"period": "2099Q2", "value": 1.27e12, "yoy_pct": 36.05, "qoq_pct": 12.0, "yoy_pp": None, "qoq_pp": None}]},
            {"key": "gross_margin", "label": "毛利率", "kind": "ratio", "definition": "d", "points": [
                {"period": "2099Q1", "value": None, "yoy_pct": None, "qoq_pct": None, "yoy_pp": None, "qoq_pp": None},
                {"period": "2099Q2", "value": 67.72, "yoy_pct": None, "qoq_pct": None, "yoy_pp": 9.1, "qoq_pp": -1.47}]},
        ],
        "monthly_revenue": [{"month": "2099-09", "revenue": 5e11, "yoy_pct": 54.6, "mom_pct": -0.6}],
        "not_applicable": [], "limitations": [],
    }
    base.update(overrides)
    return base


def _item(**overrides):
    item = {"metric_key": "gross_margin", "period": "2099Q2", "importance": "high",
            "what_happened": "毛利率來到 {{gross_margin@2099Q2}}，比去年同季 {{gross_margin@2099Q2:yoy}}。",
            "why_it_matters": "賣每樣東西賺得更多。", "how_to_read": "毛利除以營收，往上代表定價能力變強。"}
    item.update(overrides)
    return item


def test_placeholders_render_program_numbers_with_units():
    result = fc.normalize_commentary({"headline": "營收 {{revenue@2099Q2}}", "highlights": [_item()]}, _payload())
    assert result["highlights"][0]["what_happened"] == "毛利率來到 67.7%，比去年同季 +9.1 個百分點。"
    assert result["headline"] == "營收 1.27 兆元"


def test_amount_keeps_source_currency_in_token():
    payload = _payload(currency="USD")
    result = fc.normalize_commentary({"highlights": [_item(what_happened="營收 {{revenue@2099Q2}}")]}, payload)
    assert "美元" in result["highlights"][0]["what_happened"]


def test_adr_eps_token_carries_the_adr_basis():
    payload = _payload()
    payload["metrics"].append({"key": "eps", "label": "EPS", "kind": "per_share", "unit": "TWD/ADR", "definition": "d", "points": [
        {"period": "2099Q2", "value": 136.25, "yoy_pct": None, "qoq_pct": None, "yoy_pp": None, "qoq_pp": None}]})
    assert fc._token_table(payload)["eps@2099Q2"] == "136.25 元／ADR"


def test_unknown_metric_key_is_dropped():
    parsed = {"highlights": [_item(metric_key="ebitda"), _item()]}
    result = fc.normalize_commentary(parsed, _payload())
    assert [h["metric_key"] for h in result["highlights"]] == ["gross_margin"]


def test_period_without_a_value_is_dropped():
    parsed = {"highlights": [_item(period="2099Q1")]}
    assert fc.normalize_commentary(parsed, _payload()) is None


def test_invalid_importance_is_dropped():
    assert fc.normalize_commentary({"highlights": [_item(importance="critical")]}, _payload()) is None


def test_duplicate_target_keeps_first():
    result = fc.normalize_commentary({"highlights": [_item(), _item()]}, _payload())
    assert len(result["highlights"]) == 1


def test_model_written_financial_number_rejects_the_item():
    bad = _item(what_happened="毛利率來到 88.8%。")
    assert fc.normalize_commentary({"highlights": [bad]}, _payload()) is None


def test_unknown_placeholder_rejects_the_item():
    bad = _item(what_happened="毛利率 {{gross_margin@2000Q1}}")
    assert fc.normalize_commentary({"highlights": [bad]}, _payload()) is None


def test_placeholder_for_blank_cell_rejects_the_item():
    bad = _item(what_happened="上季 {{gross_margin@2099Q1}}")
    assert fc.normalize_commentary({"highlights": [bad]}, _payload()) is None


@pytest.mark.parametrize("text", ["2026 Q2 的毛利率變化", "看最近 3 個月", "去查 10-Q 附註", "近 8 季都是如此", "比較 2026-09 的數字"])
def test_non_financial_digits_are_allowed(text):
    assert fc.render_text(text, {}) == text


@pytest.mark.parametrize("text", ["毛利率 50%", "賺了 3.5 億", "每股 12 元", "翻了 2 倍"])
def test_financial_digits_are_not_allowed(text):
    assert fc.render_text(text, {}) is None


def test_highlights_are_capped():
    items = [_item(metric_key="revenue", period="2099Q1"), _item(metric_key="revenue", period="2099Q2"),
             _item(), _item(metric_key="monthly_revenue", period="2099-09")]
    with patch.object(fc, "MAX_HIGHLIGHTS", 2):
        assert len(fc.normalize_commentary({"highlights": items}, _payload())["highlights"]) == 2


def test_monthly_revenue_is_a_valid_target_with_mom_token():
    item = _item(metric_key="monthly_revenue", period="2099-09",
                 what_happened="九月營收 {{monthly_revenue@2099-09}}，月變化 {{monthly_revenue@2099-09:mom}}。")
    result = fc.normalize_commentary({"highlights": [item]}, _payload())
    assert result["highlights"][0]["what_happened"] == "九月營收 5,000.0 億元，月變化 −0.6%。"


def test_truncated_json_is_a_failure_not_repaired():
    assert fc.parse_response('{"headline": "x", "highlights": [{"metric_key": "rev') is None
    assert fc.parse_response(None) is None
    assert fc.parse_response('說明文字 {"highlights": []} 結尾') == {"highlights": []}


def test_prompt_lists_tokens_and_forbids_trade_advice():
    prompt = fc.build_prompt(_payload())
    assert "gross_margin@2099Q2:yoy" in prompt and "不做買賣建議" in prompt
    # 沒有值的格子不能出現在可用佔位符裡
    assert "gross_margin@2099Q1:yoy" not in prompt


def _points(*values):
    return [{"value": value} for value in values]


def test_trend_facts_counts_streak_and_window_extreme():
    assert fc.trend_facts(_points(1, 2, 3)) == "最新一季連續 2 季上升，是這 3 季最高"
    assert fc.trend_facts(_points(5, 1, 3, 2)) == "最新一季連續 1 季下降"
    assert fc.trend_facts(_points(3, 2, 1)) == "最新一季連續 2 季下降，是這 3 季最低"


def test_trend_facts_stops_at_a_gap_and_needs_two_points():
    assert fc.trend_facts(_points(9, None, 1, 2)) == "最新一季連續 1 季上升，是這 2 季最高"
    assert fc.trend_facts(_points(None, 1)) is None


def test_hash_ignores_monthly_revenue_but_tracks_restatement():
    base = _payload()
    next_month = _payload(monthly_revenue=[{"month": "2099-10", "revenue": 6e11, "yoy_pct": 1.0, "mom_pct": 1.0}])
    assert fc.data_hash(base) == fc.data_hash(next_month)
    restated = _payload()
    restated["metrics"][0]["points"][1]["value"] = 1.3e12
    assert fc.data_hash(base) != fc.data_hash(restated)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    from src.config import Config

    monkeypatch.setenv("STORAGE_DATABASE_URL", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    Config.reset_instance()
    DatabaseManager.reset_instance()
    fc._failures.clear()
    yield DatabaseManager.get_instance()
    DatabaseManager.reset_instance()
    Config.reset_instance()


def _enable():
    return patch("src.config.get_config", return_value=SimpleNamespace(financial_commentary_enabled=True))


def _response():
    return json.dumps({"headline": "重點", "highlights": [_item()]}, ensure_ascii=False)


def test_cache_hit_does_not_call_llm_again(storage):
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return _response(), "test-model"

    with _enable():
        first = fc.ensure_commentary(_payload(), generate=generate)
        second = fc.ensure_commentary(_payload(), generate=generate)
    assert first["status"] == second["status"] == "ready"
    assert len(calls) == 1
    assert second["model"] == "test-model" and second["highlights"][0]["metric_key"] == "gross_margin"


def test_concurrent_requests_for_same_report_call_llm_once(storage):
    """Web 與 iOS 同時開同一檔：第二個請求等第一個寫完快取，不能再付一次。"""
    calls = []
    started = threading.Event()
    release = threading.Event()

    def generate(prompt):
        calls.append(prompt)
        started.set()
        release.wait(30)
        return _response(), "m"

    results = []
    with _enable():
        first = threading.Thread(target=lambda: results.append(fc.ensure_commentary(_payload(), generate=generate)))
        first.start()
        assert started.wait(30)
        second = threading.Thread(target=lambda: results.append(fc.ensure_commentary(_payload(), generate=generate)))
        second.start()
        second.join(0.2)
        release.set()
        first.join(30)
        second.join(30)
    assert len(calls) == 1
    assert [item["status"] for item in results] == ["ready", "ready"]


def test_restated_numbers_regenerate(storage):
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return _response(), "m"

    restated = _payload()
    restated["metrics"][0]["points"][1]["value"] = 1.3e12
    with _enable():
        fc.ensure_commentary(_payload(), generate=generate)
        fc.ensure_commentary(restated, generate=generate)
    assert len(calls) == 2


def test_get_path_never_calls_llm(storage):
    with _enable(), patch.object(fc, "_llm_generate", side_effect=AssertionError("GET 不能打 LLM")):
        assert fc.cached_view(_payload())["status"] == "missing"


def test_disabled_does_not_call_llm(storage):
    with patch("src.config.get_config", return_value=SimpleNamespace(financial_commentary_enabled=False)), \
            patch.object(fc, "_llm_generate", side_effect=AssertionError("關閉時不能打 LLM")):
        assert fc.ensure_commentary(_payload())["status"] == "disabled"


def test_no_data_payload_is_not_applicable(storage):
    with _enable():
        assert fc.ensure_commentary(_payload(status="no_data"))["status"] == "not_applicable"


def test_failure_is_remembered_and_not_cached(storage):
    calls = []

    def generate(prompt):
        calls.append(prompt)
        return "not json", "m"

    with _enable():
        assert fc.ensure_commentary(_payload(), generate=generate)["status"] == "failed"
        assert fc.ensure_commentary(_payload(), generate=generate)["status"] == "failed"
        assert fc.cached_view(_payload())["status"] == "missing"
    assert len(calls) == 1


def test_llm_exception_returns_failed_status(storage):
    def generate(prompt):
        raise RuntimeError("boom")

    with _enable():
        assert fc.ensure_commentary(_payload(), generate=generate)["status"] == "failed"


def test_cached_highlight_for_removed_metric_is_filtered(storage):
    with _enable():
        fc.ensure_commentary(_payload(), generate=lambda prompt: (_response(), "m"))
    stale_key = fc._cache_key(_payload())
    with storage.session_scope() as session:
        session.query(FinancialCommentaryRecord).update({"content": json.dumps(
            {"headline": "h", "highlights": [_item(metric_key="gone")]})})
    with _enable():
        assert fc.cached_view(_payload())["status"] == "missing"
    assert stale_key["period_key"] == "2099Q2"


def test_duplicate_save_keeps_first_writer(storage):
    key = dict(stock_code="X", period_key="P", source="s", prompt_version="v", data_hash="h")
    storage.save_financial_commentary(**key, content={"a": 1}, model="first")
    storage.save_financial_commentary(**key, content={"a": 2}, model="second")
    assert storage.get_financial_commentary(**key)["model"] == "first"


def test_endpoints_expose_status_and_validate_code(storage):
    from fastapi.testclient import TestClient

    from api.app import create_app

    numbers = {key: value for key, value in _payload().items()}
    for metric in numbers["metrics"]:
        for point in metric["points"]:
            point["derived"] = False
    numbers["periods"] = [
        {"key": "2099Q1", "label": "2099 Q1", "period_end": "2099-03-31", "announce_date_kind": "statutory_deadline"},
        {"key": "2099Q2", "label": "2099 Q2", "period_end": "2099-06-30", "announce_date_kind": "statutory_deadline"}]
    numbers["metrics"][0]["unit"] = "TWD"
    numbers["metrics"][1]["unit"] = "%"
    numbers["source"] = {"id": "market.financial_statement", "label": "x", "source_unit": "新台幣千元"}
    client = TestClient(create_app())
    with patch("src.services.stock_financials.build_financials", return_value=numbers), \
            patch.object(fc, "_llm_generate", return_value=(_response(), "m")), _enable():
        got = client.get("/api/v1/stocks/2330.TW/financials")
        assert got.status_code == 200
        assert got.json()["commentary"]["status"] == "missing"
        assert got.json()["metrics"][1]["points"][1]["value"] == 67.72
        posted = client.post("/api/v1/stocks/2330.TW/financials/commentary")
        assert posted.json()["status"] == "ready"
        assert client.get("/api/v1/stocks/2330.TW/financials").json()["commentary"]["status"] == "ready"
    assert client.get("/api/v1/stocks/!!/financials").status_code == 400
