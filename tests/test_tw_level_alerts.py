"""台股 SMC 價位警報：只接受今天的 SMC 價位、預設關閉不寫入、重建時先建新再刪舊（失敗不動舊規則）、
觸發訊息是 Markdown，以及 alert_worker 只對帶 tw_level 的規則換版型。全部不碰資料庫。"""

import threading
import time

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.services import tw_level_alerts as la  # noqa: E402

SUP = {"label": "多頭 OB", "low": 1240.0, "high": 1365.0, "kind": "ob", "bias": "bull"}
RES = {"label": "空頭 OB", "low": 1395.0, "high": 1460.0, "kind": "ob", "bias": "bear"}
SUMMARY = {"name": "雙鴻", "as_of": "2026-10-21",
           "structure": {"kind": "BOS", "bias": "bear", "date": "2026-10-19", "level": 1395.0},
           "levels": [SUP, RES, {"label": "FVG 未回補", "low": 1155.0, "high": 1300.0, "kind": "fvg", "bias": "bull"},
                      {"label": "SSL 下方流動性", "low": 955.0, "high": 955.0, "kind": "ssl", "bias": "bull"}],
           "changes": [{"kind": "foreign", "tone": "pos", "text": "外資 5 日轉買 +587 張（20 日 -3,840）"}]}


def test_plan_breaks_support_low_and_resistance_high():
    rules = la.plan_rules("3324.TWO", {"support": SUP, "resistance": RES}, SUMMARY, name="雙鴻")
    assert [r["parameters"] for r in rules] == [{"direction": "below", "price": 1240.0},
                                                {"direction": "above", "price": 1460.0}]
    assert rules[0]["name"] == "雙鴻 跌破多頭 OB 1,240.00"
    assert rules[0]["cooldown_policy"] == {"cooldown_seconds": 86400}
    assert rules[1]["notification_policy"]["tw_level"]["side"] == "resistance"


@pytest.mark.parametrize("pick", [{**SUP, "low": 1000.0}, {**SUP, "kind": "fvg"}, {**SUP, "high": 1365.5}])
def test_plan_rejects_levels_not_in_todays_list(pick):
    with pytest.raises(la.LevelAlertError):
        la.plan_rules("3324.TWO", {"support": pick}, SUMMARY)


def test_plan_skips_missing_sides():
    assert la.plan_rules("3324.TWO", {"support": None, "resistance": RES}, SUMMARY)[0]["parameters"]["direction"] == "above"
    assert la.plan_rules("3324.TWO", {}, SUMMARY) == []


class FakeService:
    """假 AlertService：記錄整組替換的呼叫，delay 用來檢查同一檔的呼叫有沒有串行。"""

    def __init__(self, delay=0.0):
        self.calls, self.delay, self.active, self.max_active = [], delay, 0, 0

    def replace_source_rules(self, target, payloads, *, source):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        self.calls.append((target, [p["name"] for p in payloads], source))
        self.active -= 1
        return [{"id": 100 + i, **p} for i, p in enumerate(payloads)]


def test_replace_delegates_to_single_transaction_with_source():
    svc = FakeService()
    rules = la.plan_rules("3324.TWO", {"support": SUP}, SUMMARY, name="雙鴻")
    out = la.replace_rules("3324.TWO", rules, service=svc)
    assert svc.calls == [("3324.TWO", ["雙鴻 跌破多頭 OB 1,240.00"], "tw_levels")]
    assert out[0]["id"] == 100


def test_replace_concurrent_calls_are_serialized_per_code():
    svc = FakeService(delay=0.05)
    rules = la.plan_rules("3324.TWO", {"support": SUP, "resistance": RES}, SUMMARY, name="雙鴻")
    threads = [threading.Thread(target=la.replace_rules, args=("3324.TWO", rules), kwargs={"service": svc})
               for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(svc.calls) == 3 and svc.max_active == 1


@pytest.fixture()
def real_service(tmp_path):
    """真的 AlertService＋AlertRepository，接暫存 sqlite 檔（不碰任何正式庫）。"""
    from src.services.alert_service import AlertService
    from src.storage import DatabaseManager

    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'alerts.db'}")
    return AlertService(db_manager=db)


def _rules_by(svc, target=None, source=None):
    return [(r["target"], r["source"], r["name"]) for r in svc.list_rules(target=target, source=source, page_size=100)["items"]]


def test_transactional_replace_swaps_only_same_target_and_source(real_service):
    svc = real_service
    old = la.plan_rules("3324.TWO", {"support": SUP, "resistance": RES}, SUMMARY, name="雙鴻")
    la.replace_rules("3324.TWO", old, service=svc)
    other_code = [{**old[0], "target": "2330.TW", "name": "台積電 跌破"}]
    la.replace_rules("2330.TW", other_code, service=svc)
    svc.create_rule({**old[0], "name": "手動規則", "notification_policy": None})      # source=api，不能被刪
    new = la.plan_rules("3324.TWO", {"support": SUP}, SUMMARY, name="雙鴻")
    out = la.replace_rules("3324.TWO", new, service=svc)
    assert [r["name"] for r in out] == ["雙鴻 跌破多頭 OB 1,240.00"]
    assert _rules_by(svc, "3324.TWO", "tw_levels") == [("3324.TWO", "tw_levels", "雙鴻 跌破多頭 OB 1,240.00")]
    assert _rules_by(svc, "2330.TW", "tw_levels") == [("2330.TW", "tw_levels", "台積電 跌破")]
    assert _rules_by(svc, "3324.TWO", "api") == [("3324.TWO", "api", "手動規則")]


def test_transactional_replace_failure_keeps_old_rules_and_writes_nothing(real_service, monkeypatch):
    from src.services.alert_service import AlertServiceError

    svc = real_service
    la.replace_rules("3324.TWO", la.plan_rules("3324.TWO", {"support": SUP, "resistance": RES}, SUMMARY, name="雙鴻"),
                     service=svc)
    before = _rules_by(svc, "3324.TWO", "tw_levels")
    new = la.plan_rules("3324.TWO", {"support": SUP}, SUMMARY, name="雙鴻")
    # 1) 驗證失敗：在任何寫入之前就擋下
    with pytest.raises(AlertServiceError):
        la.replace_rules("3324.TWO", [{**new[0], "alert_type": "nope"}], service=svc)
    assert _rules_by(svc, "3324.TWO", "tw_levels") == before
    # 2) 交易中途失敗（刪舊之後、提交之前）：整組回滾，舊規則還在、也沒有半套新規則
    def boom_add_all(self, rows):
        raise RuntimeError("db hiccup mid-transaction")

    from sqlalchemy.orm import Session

    monkeypatch.setattr(Session, "add_all", boom_add_all)
    with pytest.raises(RuntimeError):
        la.replace_rules("3324.TWO", new, service=svc)
    monkeypatch.undo()
    assert _rules_by(svc, "3324.TWO", "tw_levels") == before


def test_transactional_replace_does_no_db_read_after_commit(real_service, monkeypatch):
    """提交之後不能再讀資料庫：否則連線瞬斷時規則已換掉，API 卻回 503。"""
    from sqlalchemy.orm import Session

    svc = real_service
    new = la.plan_rules("3324.TWO", {"support": SUP, "resistance": RES}, SUMMARY, name="雙鴻")
    committed = {"done": False}
    real_commit, real_refresh = Session.commit, Session.refresh

    def commit(self):
        real_commit(self)
        committed["done"] = True

    def refresh(self, *a, **kw):
        if committed["done"]:
            raise RuntimeError("disconnect after commit")
        return real_refresh(self, *a, **kw)

    monkeypatch.setattr(Session, "commit", commit)
    monkeypatch.setattr(Session, "refresh", refresh)
    out = la.replace_rules("3324.TWO", new, service=svc)
    monkeypatch.undo()
    assert [r["id"] for r in out] and all(r["source"] == "tw_levels" for r in out)
    assert sorted(("3324.TWO", r["source"], r["name"]) for r in out) == sorted(_rules_by(svc, "3324.TWO", "tw_levels"))


def test_markdown_message():
    meta = la.plan_rules("3324.TWO", {"support": SUP}, SUMMARY, name="雙鴻")[0]["notification_policy"]["tw_level"]
    md = la.format_level_alert_markdown(meta, 1236.0, SUMMARY)
    assert md.splitlines()[0] == "**🔻 雙鴻 3324.TWO 跌破多頭 OB**"
    assert "現價 **1,236**（觸發價 1,240，-0.3%）" in md
    assert "- 結構：10-19 BOS 空（1,395）" in md
    # 1236 落在多頭 FVG 1155~1300 裡：照看板語意它就是下一個支撐（距離 0），不是更遠的 SSL
    assert "- 下一個支撐：FVG 未回補 1,155~1,300（+0.0%）" in md
    assert "SSL 下方流動性" not in md
    assert "外資 5 日轉買" in md and "不是買賣訊號" in md
    # 摘要讀不到時只送價位本身
    bare = la.format_level_alert_markdown(meta, None, None)
    assert "- 結構：" not in bare and "下一個" not in bare and "多頭 OB 1,240~1,365" in bare


def test_resistance_message_looks_upward():
    meta = la.plan_rules("3324.TWO", {"resistance": RES}, SUMMARY, name="雙鴻")[0]["notification_policy"]["tw_level"]
    levels = SUMMARY["levels"] + [{"label": "BSL 上方流動性", "low": 1750.0, "high": 1750.0, "kind": "bsl", "bias": "bear"}]
    md = la.format_level_alert_markdown(meta, 1470.0, {**SUMMARY, "levels": levels})
    assert md.startswith("**🔺 雙鴻 3324.TWO 站上空頭 OB**")
    assert "- 下一個壓力：BSL 上方流動性 1,750~1,750（+19.0%）" in md


def _endpoint_client(monkeypatch, enabled):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.v1.endpoints import stocks
    from src.services import tw_stock_watch

    writes = []
    monkeypatch.setattr(stocks, "_level_alerts_enabled", lambda: enabled)
    monkeypatch.setattr(tw_stock_watch, "_one", lambda code: SUMMARY)
    monkeypatch.setattr(la, "replace_rules", lambda code, rules: writes.append(rules) or [{"id": 1}] * len(rules))
    app = FastAPI()
    app.include_router(stocks.router, prefix="/api/v1/stocks")
    return TestClient(app), writes


def test_endpoint_refuses_levels_on_old_basis_after_adjustment(monkeypatch):
    # 除權息／減資當天摘要仍是舊基準的價位：照建會建出錯的觸發價，試算也一樣擋
    from src.services import tw_stock_watch

    client, writes = _endpoint_client(monkeypatch, enabled=True)
    monkeypatch.setattr(tw_stock_watch, "_one", lambda code: {**SUMMARY, "adjusted_after": True})
    for body in ({"support": SUP}, {"support": SUP, "dry_run": True}):
        r = client.post("/api/v1/stocks/3324.TWO/level-alerts", json=body)
        assert r.status_code == 409 and r.json()["detail"]["error"] == "levels_stale"
    assert writes == []
    monkeypatch.setattr(tw_stock_watch, "_one", lambda code: {**SUMMARY, "adjusted_after": False})
    assert client.post("/api/v1/stocks/3324.TWO/level-alerts", json={"support": SUP}).status_code == 200
    assert len(writes) == 1


def test_endpoint_refuses_writes_while_disabled_but_allows_dry_run(monkeypatch):
    client, writes = _endpoint_client(monkeypatch, enabled=False)
    r = client.post("/api/v1/stocks/3324.TWO/level-alerts", json={"support": SUP})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "feature_disabled"
    r = client.post("/api/v1/stocks/3324.TWO/level-alerts", json={"support": SUP, "dry_run": True})
    assert r.status_code == 200 and r.json()["enabled"] is False and len(r.json()["rules"]) == 1
    assert writes == []


def test_endpoint_writes_when_enabled_and_validates(monkeypatch):
    client, writes = _endpoint_client(monkeypatch, enabled=True)
    r = client.post("/api/v1/stocks/3324.TWO/level-alerts", json={"support": SUP, "resistance": RES})
    assert r.status_code == 200 and r.json()["rules"] == [{"id": 1}, {"id": 1}]
    assert len(writes) == 1 and len(writes[0]) == 2
    r = client.post("/api/v1/stocks/3324.TWO/level-alerts", json={"support": {**SUP, "low": 1.0}})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "level_mismatch"
    assert client.post("/api/v1/stocks/AAPL/level-alerts", json={"support": SUP}).status_code == 400
    assert len(writes) == 1


def test_summary_exposes_flag(monkeypatch):
    from src.services import tw_stock_watch

    client, _ = _endpoint_client(monkeypatch, enabled=False)
    monkeypatch.setattr(tw_stock_watch, "summaries", lambda codes: [(c, {"as_of": "x"}, None) for c in codes])
    assert client.get("/api/v1/stocks/dossier-summary", params={"codes": "3324.TWO"}).json()["level_alerts_enabled"] is False


def test_config_flag_defaults_off(monkeypatch):
    from src.config import Config

    assert Config.__dataclass_fields__["tw_level_alerts_enabled"].default is False


def _worker(monkeypatch):
    from types import SimpleNamespace

    from src.services import alert_worker as aw

    sent = []

    class Notifier:
        def send_with_results(self, text, route_type=None):
            sent.append((text, route_type))
            return "ok"

    worker = aw.AlertWorker.__new__(aw.AlertWorker)
    worker.notifier = Notifier()
    monkeypatch.setattr(worker, "_build_analysis_visibility", lambda rule, result: {}, raising=False)
    stub_rule = SimpleNamespace(description="price cross", stock_code="3324.TWO")
    return aw, worker, stub_rule, sent


VALID_META = la.plan_rules("3324.TWO", {"support": SUP}, SUMMARY, name="雙鴻")[0]["notification_policy"]["tw_level"]


def test_worker_uses_markdown_only_for_level_rules(monkeypatch):
    aw, worker, stub_rule, sent = _worker(monkeypatch)
    monkeypatch.setattr(la, "build_level_alert_message", lambda meta, result: f"MD:{meta['code']}:{result['observed_value']}")
    rule = aw.RuntimeAlertRule(key="k", rule=stub_rule, source="db", notification_policy={"tw_level": VALID_META})
    assert worker._send_notification(rule, {"observed_value": 1236.0}) == "ok"
    assert sent == [("MD:3324.TWO:1236.0", "alert")]


@pytest.mark.parametrize("bad", [
    {**VALID_META, "high": 0}, {**VALID_META, "low": 0, "high": 0}, {**VALID_META, "low": float("nan")},
    {**VALID_META, "low": float("inf"), "high": float("inf")}, {**VALID_META, "low": 1400.0, "high": 1300.0},
    {**VALID_META, "side": "sideways"}, {**VALID_META, "code": "AAPL"}, {**VALID_META, "low": "abc"},
    {**VALID_META, "low": "1240", "high": "1365"}, {**VALID_META, "low": True, "high": 1365.0},
    {k: v for k, v in VALID_META.items() if k != "label"}, {"code": "3324.TWO"}, {},
])
def test_worker_falls_back_to_generic_for_invalid_meta(monkeypatch, bad):
    aw, worker, stub_rule, sent = _worker(monkeypatch)

    def boom(meta, result):
        raise AssertionError("Markdown 版型不該收到不合法的 meta")

    monkeypatch.setattr(la, "build_level_alert_message", boom)
    rule = aw.RuntimeAlertRule(key="k", rule=stub_rule, source="db", notification_policy={"tw_level": bad})
    assert worker._send_notification(rule, {"observed_value": 1236.0, "reason": "跌破 1240"}) == "ok"
    assert len(sent) == 1 and "跌破 1240" in sent[0][0] and sent[0][1] == "alert"


def test_valid_meta_accepts_point_levels_and_both_sides():
    assert la.valid_level_meta(VALID_META)
    assert la.valid_level_meta({**VALID_META, "side": "resistance", "low": 955.0, "high": 955.0})
    assert la.valid_level_meta({**VALID_META, "code": "00631L.TW"})
    assert la.valid_level_meta({**VALID_META, "low": 1240, "high": 1365})      # int 也是數字


# 下一個價位：與前端 nearestLevels 同語意，排除剛觸發的那個
def _lv(label, low, high, kind, bias):
    return {"label": label, "low": low, "high": high, "kind": kind, "bias": bias}


def test_next_support_excludes_the_level_that_just_broke():
    # 1350 仍在 SUP 1240~1365 裡（多頭、距離 0），但它就是剛觸發的那個，要跳過
    nxt = la._next_level(SUMMARY, VALID_META, 1350.0)
    assert nxt["kind"] == "fvg" and round(nxt["dist"], 1) == -3.7


def test_next_support_counts_bull_zone_containing_price_as_zero_distance():
    nxt = la._next_level(SUMMARY, VALID_META, 1236.0)
    assert nxt["label"] == "FVG 未回補" and nxt["dist"] == 0.0


def test_next_level_ignores_zones_containing_price_with_wrong_or_no_bias():
    levels = [SUP, _lv("空頭 OB", 1200.0, 1260.0, "ob", "bear"), _lv("OTE", 1220.0, 1250.0, "ote", None),
              _lv("SSL", 955.0, 955.0, "ssl", "bull")]
    nxt = la._next_level({"levels": levels}, VALID_META, 1236.0)
    assert nxt["label"] == "SSL"
    res_meta = {**VALID_META, "side": "resistance", **{k: RES[k] for k in ("label", "low", "high", "kind", "bias")}}
    levels = [RES, _lv("多頭 FVG", 1460.0, 1500.0, "fvg", "bull"), _lv("BSL", 1750.0, 1750.0, "bsl", "bear")]
    assert la._next_level({"levels": levels}, res_meta, 1470.0)["label"] == "BSL"
    levels.append(_lv("空頭 FVG", 1465.0, 1480.0, "fvg", "bear"))
    nxt = la._next_level({"levels": levels}, res_meta, 1470.0)
    assert nxt["label"] == "空頭 FVG" and nxt["dist"] == 0.0


def test_next_level_keeps_same_kind_level_at_other_prices():
    other_ob = _lv("多頭 OB", 1100.0, 1200.0, "ob", "bull")
    nxt = la._next_level({"levels": [SUP, other_ob]}, VALID_META, 1236.0)
    assert nxt["low"] == 1100.0 and round(nxt["dist"], 1) == -2.9


# 除權息：價位以 as_of 前復權，之後有事件就提醒重建
def test_message_warns_when_adjustment_after_as_of(monkeypatch):
    from src.services import tw_stock_watch

    calls = []
    monkeypatch.setattr(tw_stock_watch, "_one", lambda code: SUMMARY)
    monkeypatch.setattr(la, "_adjusted_after", lambda code, as_of: calls.append((code, as_of)) or True)
    md = la.build_level_alert_message(VALID_META, {"observed_value": 1236.0})
    assert md.splitlines()[0] == "⚠️ 價位建立後（2026-10-21）有除權息，價位基準已變動，請等盤後資料更新後在盯盤看板重建警報"
    assert calls == [("3324.TWO", "2026-10-21")]
    monkeypatch.setattr(la, "_adjusted_after", lambda code, as_of: False)
    md = la.build_level_alert_message(VALID_META, {"observed_value": 1236.0})
    assert "除權息" not in md and md.startswith("**🔻")


def test_adjustment_lookup_fails_open_and_queries_after_as_of(monkeypatch):
    import pandas as pd

    from market_data import market_repo

    seen = []

    def fake(stock_id, start=None, end=None, **kw):
        seen.append((stock_id, str(start)))
        return pd.Series([0.95], index=[pd.Timestamp("2026-10-22")]) if start.isoformat() > "2026-10-21" else pd.Series(dtype=float)

    monkeypatch.setattr(market_repo, "adjustment_multipliers", fake)
    assert la._adjusted_after("3324.TWO", "2026-10-21") is True
    assert seen == [("3324", "2026-10-22")]

    monkeypatch.setattr(market_repo, "adjustment_multipliers", lambda *a, **k: pd.Series(dtype=float))
    assert la._adjusted_after("3324.TWO", "2026-10-21") is False

    def down(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(market_repo, "adjustment_multipliers", down)
    assert la._adjusted_after("3324.TWO", "2026-10-21") is False


# 端點錯誤對應
def test_endpoint_maps_write_errors(monkeypatch):
    from src.services.alert_service import AlertServiceError

    client, _ = _endpoint_client(monkeypatch, enabled=True)

    def bad_rule(code, rules):
        raise AlertServiceError("bad payload")

    monkeypatch.setattr(la, "replace_rules", bad_rule)
    r = client.post("/api/v1/stocks/3324.TWO/level-alerts", json={"support": SUP})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "invalid_rule"

    def db_down(code, rules):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(la, "replace_rules", db_down)
    r = client.post("/api/v1/stocks/3324.TWO/level-alerts", json={"support": SUP})
    assert r.status_code == 503 and r.json()["detail"]["error"] == "level_alerts_unavailable"
    assert "connection refused" not in r.text


def test_endpoint_level_mismatch_and_not_found_still_mapped(monkeypatch):
    from src.services import tw_stock_watch

    client, _ = _endpoint_client(monkeypatch, enabled=True)
    r = client.post("/api/v1/stocks/3324.TWO/level-alerts", json={"support": {**SUP, "low": 1.0}})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "level_mismatch"

    def missing(code):
        raise LookupError("no rows")

    monkeypatch.setattr(tw_stock_watch, "_one", missing)
    r = client.post("/api/v1/stocks/3324.TWO/level-alerts", json={"support": SUP})
    assert r.status_code == 404 and r.json()["detail"]["error"] == "not_found"

    def market_db_down(code):
        raise RuntimeError("market db timeout")

    monkeypatch.setattr(tw_stock_watch, "_one", market_db_down)
    r = client.post("/api/v1/stocks/3324.TWO/level-alerts", json={"support": SUP, "dry_run": True})
    assert r.status_code == 503 and r.json()["detail"]["error"] == "level_alerts_unavailable"
    assert "market db timeout" not in r.text


def test_dossier_rejects_impossible_date(monkeypatch):
    from src.services import tw_stock_report

    client, _ = _endpoint_client(monkeypatch, enabled=False)
    seen = []
    monkeypatch.setattr(tw_stock_report, "report_html", lambda code, **kw: seen.append(kw["as_of"]) or "<html></html>")
    r = client.get("/api/v1/stocks/3324.TWO/dossier", params={"date": "2026-13-45"})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "invalid_date"
    r = client.get("/api/v1/stocks/3324.TWO/dossier", params={"date": "2026-02-30"})
    assert r.status_code == 400
    assert client.get("/api/v1/stocks/3324.TWO/dossier", params={"date": "2026-10-21"}).status_code == 200
    assert client.get("/api/v1/stocks/3324.TWO/dossier").status_code == 200
    assert seen == ["2026-10-21", None]


@pytest.mark.parametrize("enabled,read_only,expected", [
    (False, False, ["generic"]), (True, False, ["generic", "levels"]), (False, True, ["generic", "levels"]),
])
def test_worker_skips_level_rules_while_flag_is_off(monkeypatch, enabled, read_only, expected):
    # 開關關掉後，之前建好的價位規則不再評估、不推；唯讀的規則來源統計照列
    from types import SimpleNamespace

    from src.services import alert_worker as aw

    rows = [SimpleNamespace(id=1, source="manual", name="generic", cooldown_policy=None, notification_policy=None,
                            severity="info"),
            SimpleNamespace(id=2, source=la.SOURCE, name="levels", cooldown_policy=None, notification_policy=None,
                            severity="info")]
    service = SimpleNamespace(
        repo=SimpleNamespace(list_enabled_rules=lambda limit: rows),
        _load_json=lambda v, default=None: default,
        build_runtime_payloads=lambda row, **kw: [SimpleNamespace(key=row.name, rule=row, effective_target=None,
                                                                 display_target=None)],
    )
    worker = aw.AlertWorker.__new__(aw.AlertWorker)
    worker.service = service
    loaded = worker._load_runtime_rules(SimpleNamespace(tw_level_alerts_enabled=enabled), read_only=read_only)
    assert [r.key for r in loaded] == expected
