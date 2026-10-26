"""盯盤看板四維度摘要：價位清單、近一日變化的觸發條件、批次端點的單檔失敗不拖垮整批。"""

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.services import tw_stock_watch as watch  # noqa: E402
from src.services.tw_stock_report import NARRATIVE_CHECK_VERSION as VERSION, data_stamp  # noqa: E402

SMC = {"price": 100.0, "bsl": [140.0, 112.0], "ssl": [90.0],
       "order_blocks": [{"direction": "bullish", "low": 95.0, "high": 98.0},
                        {"direction": "bearish", "low": 104.0, "high": 106.0}],
       "fvgs": [{"direction": "bearish", "low": 101.0, "high": 102.0}],
       "fib": {"ote_low": 108.0, "ote_high": 109.0},
       "last_event": {"date": "2026-10-21 00:00:00", "kind": "CHOCH", "direction": "bearish", "level": 99.5}}


def payload(**over):
    p = {"stock_id": "3324", "as_of": "2026-10-21", "smc": SMC, "errors": [],
         "fundamentals": {"monthly_revenue": [{"month": "2026-09", "yoy_pct": 23.22, "announced": "2026-10-10"}]},
         "chips": {"institutional": {"as_of": "2026-10-21", "foreign_5d_lots": 587, "foreign_20d_lots": -3840},
                   "holding": {"big_holder_pct_wow": -0.3, "as_of": "2026-10-16"}}}
    p.update(over)
    return p


def test_levels_carry_bias_and_drop_far_ones():
    lv = watch.smc_levels(SMC)
    assert {(x["kind"], x["bias"]) for x in lv} == {
        ("bsl", "bear"), ("ssl", "bull"), ("ob", "bull"), ("ob", "bear"), ("fvg", "bear"), ("ote", "bear")}
    assert 140.0 not in [x["high"] for x in lv]          # +40% 太遠
    assert 112.0 in [x["high"] for x in lv]
    assert watch.smc_levels(None) == []


@pytest.mark.parametrize("event, bias, label", [
    ({"direction": "bullish"}, "bull", "OTE 多方進場區"),
    ({"direction": "bearish"}, "bear", "OTE 空方進場區"),
    (None, None, "OTE 進場區"),
])
def test_ote_direction_follows_last_event(event, bias, label):
    ote = [x for x in watch.smc_levels({**SMC, "last_event": event}) if x["kind"] == "ote"]
    assert [(x["bias"], x["label"]) for x in ote] == [(bias, label)]


def test_revenue_change_text_uses_slash_date_and_plain_month():
    texts = [c["text"] for c in watch._changes(payload(as_of="2026-10-17")) if c["kind"] == "revenue"]
    assert texts == ["10/10 9 月營收 YoY +23.2%"]


def test_changes_dated_by_last_session():
    texts = [c["text"] for c in watch._changes(payload())]
    assert texts == ["10-21 ChoCH 轉空（99.5）", "10-21 外資 5 日轉買 +587 張（20 日 -3,840）"]


@pytest.mark.parametrize("metadata, current", [
    ({"as_of": "2026-10-21"}, True),
    ({"as_of": "2026-10-20"}, False),
    ({"as_of": "2026-10-22"}, False),
    ({"as_of": None}, False),
    ({"as_of": ""}, False),
    ({}, False),
])
@pytest.mark.parametrize("f5, f20, tone, text", [
    (587, -3840, "pos", "10-21 外資 5 日轉買 +587 張（20 日 -3,840）"),
    (-5, 10, "neg", "10-21 外資 5 日轉賣 -5 張（20 日 +10）"),
])
def test_summary_foreign_flip_requires_matching_data_date(metadata, current, f5, f20, tone, text):
    p = payload(chips={"institutional": {**metadata, "foreign_5d_lots": f5, "foreign_20d_lots": f20}})
    changes = watch.summarize(p)["changes"]
    assert [c for c in changes if c["kind"] == "foreign"] == (
        [{"kind": "foreign", "tone": tone, "text": text}] if current else [])
    # 法人落後時只省略外資提示，同日的結構變化照常保留。
    assert [c["text"] for c in changes if c["kind"] == "structure"] == ["10-21 ChoCH 轉空（99.5）"]


@pytest.mark.parametrize("over, kind, expected", [
    # 結構事件不是最近一個交易日 -> 不提示
    ({"smc": {**SMC, "last_event": {**SMC["last_event"], "date": "2026-10-20"}}}, "structure", False),
    # 營收在 as_of 前 7 天內公告 -> 提示；第 8 天就不提示
    ({"as_of": "2026-10-17"}, "revenue", True),
    ({"as_of": "2026-10-18"}, "revenue", False),
    # 外資 5 日與 20 日同向 -> 不算轉向
    ({"chips": {"institutional": {"as_of": "2026-10-21", "foreign_5d_lots": 587, "foreign_20d_lots": 3840}}}, "foreign", False),
    ({"chips": {"institutional": {"as_of": "2026-10-21", "foreign_5d_lots": -5, "foreign_20d_lots": 10}}}, "foreign", True),
    # 千張大戶週變化 ±0.5pp 才提示
    ({"chips": {"holding": {"big_holder_pct_wow": 0.5, "as_of": "2026-10-16"}}}, "holder", True),
    ({"chips": {"holding": {"big_holder_pct_wow": -0.49, "as_of": "2026-10-16"}}}, "holder", False),
    ({"errors": ["估值"]}, "error", True),
])
def test_change_conditions(over, kind, expected):
    assert (kind in [c["kind"] for c in watch._changes(payload(**over))]) is expected


def test_summarize_shape_and_cached_verdicts():
    s = watch.summarize(payload(), {"verdicts": {"chips": {"badge": "外資調節", "tone": "neg", "note": "x"}},
                                    "check_version": VERSION, "data_stamp": data_stamp(payload())})
    assert s["close"] == 100.0 and s["as_of"] == "2026-10-21"
    assert s["structure"] == {"kind": "ChoCH", "bias": "bear", "date": "2026-10-21", "level": 99.5}
    assert s["verdicts"] == {"chips": {"badge": "外資調節", "tone": "neg"}}
    assert watch.summarize(payload(smc=None))["structure"] is None
    assert watch.summarize(payload())["verdicts"] is None


def test_summarize_hides_verdicts_from_unverified_narrative():
    nar = {"verdicts": {"chips": {"badge": "外資調節", "tone": "neg"}}, "check_version": VERSION,
           "data_stamp": data_stamp(payload())}
    assert watch.summarize(payload(), {**nar, "unverified": ["41.27"]})["verdicts"] is None
    # 空清單代表全部核對過，照常顯示
    assert watch.summarize(payload(), {**nar, "unverified": []})["verdicts"] == nar["verdicts"]
    # 舊版核對規則寫的快取（沒有或不同的 check_version）也不上看板
    assert watch.summarize(payload(), {"verdicts": nar["verdicts"]})["verdicts"] is None
    assert watch.summarize(payload(), {**nar, "check_version": VERSION - 1})["verdicts"] is None
    # 解讀寫完之後同一基準日的資料又更新（例如法人晚入庫）：舊結論不上看板
    assert watch.summarize(payload(), {**nar, "data_stamp": "stale"})["verdicts"] is None


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


@pytest.fixture(autouse=True)
def _no_market_db(monkeypatch):
    # _one 會查 market.price_adjustment；單元測試不連行情庫
    monkeypatch.setattr(watch, "_adjusted_since", lambda code, as_of: False)


def test_one_flags_adjustment_after_as_of_and_caches_the_lookup(monkeypatch):
    from src.services import tw_stock_dossier

    calls, events = [], {"3324.TWO"}
    monkeypatch.setattr(watch, "_summary_cache", {})
    monkeypatch.setattr(watch, "_cached_verdicts", lambda p: None)
    monkeypatch.setattr(watch, "_adjusted_since", lambda code, as_of: calls.append((code, as_of)) or code in events)
    monkeypatch.setattr(tw_stock_dossier, "build", lambda code, **kw: payload())
    assert watch._one("3324.TWO")["adjusted_after"] is True
    assert watch._one("3324.TWO")["adjusted_after"] is True
    assert watch._one("2330.TW")["adjusted_after"] is False
    # 查的是資料包的 as_of 之後；同一檔 10 分鐘內只查一次
    assert calls == [("3324.TWO", "2026-10-21"), ("2330.TW", "2026-10-21")]


def test_one_skips_branch_fetch_and_caches(monkeypatch):
    from src.services import tw_stock_dossier

    calls = []
    monkeypatch.setattr(watch, "_summary_cache", {})
    monkeypatch.setattr(watch, "_cached_verdicts", lambda p: None)
    monkeypatch.setattr(tw_stock_dossier, "build", lambda code, **kw: calls.append(kw) or payload())
    watch._one("3324.TWO")
    watch._one("3324.TWO")
    assert calls == [{"branch": False}]      # 看板每檔不打富邦，且 10 分鐘內不重算


def test_one_rereads_verdicts_within_ttl(monkeypatch):
    from src.services import tw_stock_dossier

    calls, nar = [], {"v": None}
    monkeypatch.setattr(watch, "_summary_cache", {})
    monkeypatch.setattr(watch, "_cached_verdicts", lambda p: nar["v"])
    monkeypatch.setattr(tw_stock_dossier, "build", lambda code, **kw: calls.append(code) or payload())
    assert watch._one("3324.TWO")["verdicts"] is None
    # 一分鐘後解讀產生了：資料包仍走快取，但色調要立刻出現
    nar["v"] = {"verdicts": {"chips": {"badge": "外資調節", "tone": "neg"}}, "check_version": VERSION,
                "data_stamp": data_stamp(payload())}
    assert watch._one("3324.TWO")["verdicts"] == {"chips": {"badge": "外資調節", "tone": "neg"}}
    assert calls == ["3324.TWO"]


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
