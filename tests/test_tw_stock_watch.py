"""盯盤看板四維度摘要：價位清單、近一日變化的觸發條件、批次端點的單檔失敗不拖垮整批。"""

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.services import tw_stock_watch as watch  # noqa: E402

SMC = {"price": 100.0, "bsl": [140.0, 112.0], "ssl": [90.0],
       "order_blocks": [{"direction": "bullish", "low": 95.0, "high": 98.0},
                        {"direction": "bearish", "low": 104.0, "high": 106.0}],
       "fvgs": [{"direction": "bearish", "low": 101.0, "high": 102.0}],
       "fib": {"ote_low": 108.0, "ote_high": 109.0},
       "last_event": {"date": "2026-10-21 00:00:00", "kind": "CHOCH", "direction": "bearish", "level": 99.5}}


def payload(**over):
    p = {"stock_id": "3324", "as_of": "2026-10-21", "smc": SMC, "errors": [],
         "fundamentals": {"monthly_revenue": [{"month": "2026-09", "yoy_pct": 23.22, "announced": "2026-10-10"}]},
         "chips": {"institutional": {"foreign_5d_lots": 587, "foreign_20d_lots": -3840},
                   "holding": {"big_holder_pct_wow": -0.3, "as_of": "2026-10-16"}}}
    p.update(over)
    return p


def test_levels_carry_bias_and_drop_far_ones():
    lv = watch.smc_levels(SMC)
    assert {(x["kind"], x["bias"]) for x in lv} == {
        ("bsl", "bear"), ("ssl", "bull"), ("ob", "bull"), ("ob", "bear"), ("fvg", "bear"), ("ote", None)}
    assert 140.0 not in [x["high"] for x in lv]          # +40% 太遠
    assert 112.0 in [x["high"] for x in lv]
    assert watch.smc_levels(None) == []


def test_changes_dated_by_last_session():
    texts = [c["text"] for c in watch._changes(payload())]
    assert texts == ["10-21 ChoCH 轉空（99.5）", "外資 5 日轉買 +587 張（20 日 -3,840）"]


@pytest.mark.parametrize("over, kind, expected", [
    # 結構事件不是最近一個交易日 -> 不提示
    ({"smc": {**SMC, "last_event": {**SMC["last_event"], "date": "2026-10-20"}}}, "structure", False),
    # 營收在 as_of 前 7 天內公告 -> 提示；第 8 天就不提示
    ({"as_of": "2026-10-17"}, "revenue", True),
    ({"as_of": "2026-10-18"}, "revenue", False),
    # 外資 5 日與 20 日同向 -> 不算轉向
    ({"chips": {"institutional": {"foreign_5d_lots": 587, "foreign_20d_lots": 3840}}}, "foreign", False),
    ({"chips": {"institutional": {"foreign_5d_lots": -5, "foreign_20d_lots": 10}}}, "foreign", True),
    # 千張大戶週變化 ±0.5pp 才提示
    ({"chips": {"holding": {"big_holder_pct_wow": 0.5, "as_of": "2026-10-16"}}}, "holder", True),
    ({"chips": {"holding": {"big_holder_pct_wow": -0.49, "as_of": "2026-10-16"}}}, "holder", False),
    ({"errors": ["估值"]}, "error", True),
])
def test_change_conditions(over, kind, expected):
    assert (kind in [c["kind"] for c in watch._changes(payload(**over))]) is expected


def test_summarize_shape_and_cached_verdicts():
    s = watch.summarize(payload(), {"verdicts": {"chips": {"badge": "外資調節", "tone": "neg", "note": "x"}}})
    assert s["close"] == 100.0 and s["as_of"] == "2026-10-21"
    assert s["structure"] == {"kind": "ChoCH", "bias": "bear", "date": "2026-10-21", "level": 99.5}
    assert s["verdicts"] == {"chips": {"badge": "外資調節", "tone": "neg"}}
    assert watch.summarize(payload(smc=None))["structure"] is None
    assert watch.summarize(payload())["verdicts"] is None


def test_summaries_isolate_failures(monkeypatch):
    def one(code):
        if code == "9999.TW":
            raise LookupError("no price")
        if code == "1111.TW":
            raise RuntimeError("db hiccup")
        return {"as_of": "2026-10-21"}

    monkeypatch.setattr(watch, "_one", one)
    assert watch.summaries(["3324.TWO", "9999.TW", "1111.TW"]) == [
        ("3324.TWO", {"as_of": "2026-10-21"}, None), ("9999.TW", None, "no_data"), ("1111.TW", None, "unavailable")]


def test_one_skips_branch_fetch_and_caches(monkeypatch):
    from src.services import tw_stock_dossier

    calls = []
    monkeypatch.setattr(watch, "_summary_cache", {})
    monkeypatch.setattr(watch, "_cached_verdicts", lambda p: None)
    monkeypatch.setattr(tw_stock_dossier, "build", lambda code, **kw: calls.append(kw) or payload())
    watch._one("3324.TWO")
    watch._one("3324.TWO")
    assert calls == [{"branch": False}]      # 看板每檔不打富邦，且 10 分鐘內不重算


def test_summary_endpoint_batch(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.v1.endpoints import stocks

    seen = []
    monkeypatch.setattr(watch, "summaries", lambda codes: seen.append(codes) or [(c, {"as_of": "x"}, None) for c in codes])
    app = FastAPI()
    app.include_router(stocks.router, prefix="/api/v1/stocks")
    client = TestClient(app)
    r = client.get("/api/v1/stocks/dossier-summary", params={"codes": "3324.two, AAPL,3324.TWO,,2330.TW"})
    assert r.status_code == 200
    assert [(i["stock_code"], i["error"]) for i in r.json()["items"]] == [
        ("3324.TWO", None), ("AAPL", "unsupported_market"), ("2330.TW", None)]
    assert seen == [["3324.TWO", "2330.TW"]]
    # 上限用原始輸入計算：同一檔重複 51 次也擋
    r = client.get("/api/v1/stocks/dossier-summary", params={"codes": ",".join(["2330.TW"] * 51)})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "too_many_codes"
    assert client.get("/api/v1/stocks/dossier-summary", params={"codes": " , "}).status_code == 400
