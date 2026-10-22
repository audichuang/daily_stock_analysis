"""台股 SMC 價位警報：只接受今天的 SMC 價位、預設關閉不寫入、重建前先刪舊規則、
觸發訊息是 Markdown，以及 alert_worker 只對帶 tw_level 的規則換版型。全部不碰資料庫。"""

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
    def __init__(self, existing):
        self.existing, self.deleted, self.created = existing, [], []

    def list_rules(self, **kw):
        self.list_kw = kw
        return {"items": self.existing}

    def delete_rule(self, rule_id):
        self.deleted.append(rule_id)
        return True

    def create_rule(self, payload, *, source):
        self.created.append((payload["name"], source))
        return {"id": 100 + len(self.created), **payload}


def test_replace_deletes_old_level_rules_then_creates_with_source():
    svc = FakeService([{"id": 7}, {"id": 9}])
    rules = la.plan_rules("3324.TWO", {"support": SUP}, SUMMARY, name="雙鴻")
    out = la.replace_rules("3324.TWO", rules, service=svc)
    assert svc.list_kw["target"] == "3324.TWO" and svc.list_kw["source"] == "tw_levels"
    assert svc.deleted == [7, 9]
    assert svc.created == [("雙鴻 跌破多頭 OB 1,240.00", "tw_levels")]
    assert out[0]["id"] == 101


def test_markdown_message():
    meta = la.plan_rules("3324.TWO", {"support": SUP}, SUMMARY, name="雙鴻")[0]["notification_policy"]["tw_level"]
    md = la.format_level_alert_markdown(meta, 1236.0, SUMMARY)
    assert md.splitlines()[0] == "**🔻 雙鴻 3324.TWO 跌破多頭 OB**"
    assert "現價 **1,236**（觸發價 1,240，-0.3%）" in md
    assert "- 結構：10-19 BOS 空（1,395）" in md
    assert "- 下一個支撐：FVG 未回補 1,155~1,300（+5.2%）" not in md     # 1300 不在 1236 之下
    assert "- 下一個支撐：SSL 下方流動性 955~955（-22.7%）" in md
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


def test_worker_uses_markdown_only_for_level_rules(monkeypatch):
    from src.services import alert_worker as aw

    sent = []

    class Notifier:
        def send_with_results(self, text, route_type=None):
            sent.append((text, route_type))
            return "ok"

    monkeypatch.setattr(la, "build_level_alert_message", lambda meta, result: f"MD:{meta['code']}:{result['observed_value']}")
    worker = aw.AlertWorker.__new__(aw.AlertWorker)
    worker.notifier = Notifier()
    meta = {"code": "3324.TWO"}
    rule = aw.RuntimeAlertRule(key="k", rule=None, source="db", notification_policy={"tw_level": meta})
    assert worker._send_notification(rule, {"observed_value": 1236.0}) == "ok"
    assert sent == [("MD:3324.TWO:1236.0", "alert")]
