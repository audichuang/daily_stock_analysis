"""個股 HTML 報告：缺資料印「無資料」、解讀文字一律跳脫、價位階梯標籤不重疊、
LLM 解讀格式不對就降級、只收台股代號。"""

import json
import re

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.services import tw_stock_report as report  # noqa: E402

EMPTY = {"stock_id": "9999", "name": None, "as_of": "2026-08-28",
         "fundamentals": {"monthly_revenue": [], "ttm_revenue_yoy_pct": None, "quarters": []},
         "contract_liabilities": [],
         "chips": {"institutional": None, "margin": None, "holding": None, "branch": None},
         "valuation": None, "smc": None}


def test_every_section_missing_renders_no_data():
    html = report.render(EMPTY)
    assert html.count(report.NA) >= 8
    assert "未附解讀" in html and "四維度總覽" not in html


def test_narrative_text_is_escaped():
    nar = {"verdicts": {"chips": {"badge": "<b>x</b>", "tone": "pos", "note": "<script>alert(1)</script>"}},
           "followups": ["a<i>"]}
    html = report.render(EMPTY, nar)
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "<b>x</b>" not in html and "a&lt;i&gt;" in html


def test_ladder_labels_do_not_overlap():
    smc = {"price": 100.0, "bsl": [110.0], "ssl": [99.5, 99.0],
           "order_blocks": [{"direction": "bullish", "low": 98.0, "high": 100.5}],
           "fvgs": [{"direction": "bullish", "low": 99.2, "high": 99.8}], "fib": None}
    tops = [float(x) for x in re.findall(r'class="ltag(?: now)?" style="top:([\d.]+)px', report._ladder(smc))]
    assert len(tops) == 6      # 5 levels + 現價
    assert all(b - a >= 17.8 for a, b in zip(tops, tops[1:]))


GOOD = {"verdicts": {k: {"badge": "b", "tone": "neu", "note": "n"} for k in report.VERDICTS},
        "notes": {"revenue": "觀察：x"}, "followups": ["f"]}


def test_parse_narrative_accepts_json_wrapped_in_prose():
    nar = report.parse_narrative("好的，以下是結果：\n```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```")
    assert nar["verdicts"]["chips"]["note"] == "n"


def test_parse_narrative_repairs_trailing_comma():
    broken = json.dumps(GOOD, ensure_ascii=False)[:-1] + ",}"
    assert report.parse_narrative(broken)["followups"] == ["f"]


@pytest.mark.parametrize("text", [None, "", "not json", "{broken", json.dumps({"verdicts": {}}),
                                  json.dumps({"verdicts": {**GOOD["verdicts"], "valuation": {"badge": "b"}}})])
def test_parse_narrative_rejects_incomplete(text):
    assert report.parse_narrative(text) is None


def _payload_stub(monkeypatch):
    monkeypatch.setattr(report, "_payload", lambda code, as_of: {**EMPTY, "stock_id": code.split(".")[0]})


def test_report_html_caches_narrative_per_as_of(monkeypatch, tmp_path):
    _payload_stub(monkeypatch)
    calls = []

    def gen(prompt):
        calls.append(prompt)
        return json.dumps(GOOD)

    for _ in range(2):
        html = report.report_html("3324.two", narrative=True, generate=gen, cache_dir=tmp_path)
    assert len(calls) == 1 and "資料包" in calls[0]
    assert "四維度總覽" in html and "AI 解讀產生失敗" not in html
    assert (tmp_path / "3324_2026-08-28.json").exists()


@pytest.mark.parametrize("gen", [lambda p: "抱歉無法回答", lambda p: (_ for _ in ()).throw(RuntimeError("down"))])
def test_report_html_llm_failure_degrades_to_numbers(monkeypatch, tmp_path, gen):
    _payload_stub(monkeypatch)
    html = report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    assert "AI 解讀產生失敗" in html and "四維度總覽" not in html
    assert not list(tmp_path.iterdir())      # 失敗不寫快取


@pytest.mark.parametrize("code", ["AAPL", "3324", "600519.SH", "３３２４.TW"])
def test_report_html_rejects_non_tw_codes(monkeypatch, code):
    _payload_stub(monkeypatch)
    with pytest.raises(report.UnsupportedMarket):
        report.report_html(code)


def test_dossier_endpoint_maps_errors(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.v1.endpoints.stocks import router

    real = report.report_html

    def boom(code, **kw):
        if code == "3324.TWO":
            raise ValueError("pandas parse error deep in build()")
        return real(code, **kw)

    monkeypatch.setattr(report, "report_html", boom)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/stocks")
    client = TestClient(app)
    r = client.get("/api/v1/stocks/AAPL/dossier")
    assert r.status_code == 400 and r.json()["detail"]["error"] == "unsupported_market"
    r = client.get("/api/v1/stocks/3324.TWO/dossier")
    assert r.status_code == 503 and r.json()["detail"]["error"] == "dossier_unavailable"
    assert client.get("/api/v1/stocks/2330.TW/dossier", params={"date": "２０２６-08-28"}).status_code == 422


def test_report_html_theme_attr(monkeypatch):
    _payload_stub(monkeypatch)
    assert '<html lang="zh-Hant" data-theme="dark">' in report.report_html("2330.TW", theme="dark")
    assert '<html lang="zh-Hant"><head>' in report.report_html("2330.TW", theme="evil\"><script>")


def test_unverified_numbers_flags_only_numbers_missing_from_payload():
    p = {**EMPTY, "valuation": {"pe": 26.29, "as_of": "2026-08-28"}, "smc": {"price": 1375.0, "fib": {"position": 0.128}}}
    nar = {"verdicts": {"valuation": {"note": "本益比 26.29 倍，現價 1,375.0，Fib 12.8%；外資持股 41.27%。"}},
           "notes": {"valuation": "以 EPS 自算本益比約 31.4 倍。"}}
    assert report.unverified_numbers(nar, p) == ["41.27"]


def test_unverified_narrative_is_shown_with_notice_but_not_cached(monkeypatch, tmp_path):
    _payload_stub(monkeypatch)
    bad = {**GOOD, "notes": {"chips": "外資持股 41.27%。"}}
    calls = []

    def gen(prompt):
        calls.append(prompt)
        return json.dumps(bad, ensure_ascii=False)

    html = report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    assert "四維度總覽" in html and "41.27" in html and "無法在資料包核對" in html
    assert not list(tmp_path.iterdir())
    report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    assert len(calls) == 2      # 沒快取，下次重寫


def test_failed_sections_are_listed_in_notice(monkeypatch):
    monkeypatch.setattr(report, "_payload", lambda code, as_of: {**EMPTY, "errors": ["估值", "技術面"]})
    assert "讀取失敗、以「無資料」呈現的段落：估值、技術面" in report.report_html("2330.TW")


def test_llm_generate_tags_usage_as_stock_dossier(monkeypatch):
    from src import analyzer as analyzer_mod

    seen = {}

    class FakeAnalyzer:
        def __init__(self, config):
            pass

        def is_available(self):
            return True

        def generate_text(self, prompt, **kw):
            seen.update(kw)
            return "{}"

    monkeypatch.setattr(analyzer_mod, "GeminiAnalyzer", FakeAnalyzer)
    report._llm_generate("x")
    assert seen["call_type"] == "stock_dossier"


def test_generate_text_persists_given_call_type(monkeypatch):
    from unittest.mock import patch

    from src.analyzer import GeminiAnalyzer

    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    with patch.object(analyzer, "_call_litellm", return_value=("ok", "m", {"total_tokens": 1})), \
         patch("src.analyzer.should_persist_usage_telemetry", return_value=True), \
         patch("src.analyzer.persist_llm_usage") as persist:
        assert analyzer.generate_text("p") == "ok"
        assert analyzer.generate_text("p", call_type="stock_dossier") == "ok"
    assert [c.kwargs["call_type"] for c in persist.call_args_list] == ["market_review", "stock_dossier"]
