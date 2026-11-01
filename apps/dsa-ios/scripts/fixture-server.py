#!/usr/bin/env python3
"""僅供 iOS 驗收的 loopback HTTP fixture；行情為固定過去日期，行事曆使用相對日期，均為合成資料。"""

import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit


AS_OF = "2024-01-31T13:30:00+08:00"
FIXTURE_PASSWORD = "fixture-password"
FIXTURE_COOKIE = "fixture-session-only"
QUOTE_DELAY = 0.0
DAILY_TREND_DELAY = 0.0
STOCKS = {
    "2330.TW": ("台積電（測試）", 600.0, 1.69, "tw"),
    "2317.TW": ("鴻海（測試）", 100.0, -0.99, "tw"),
    "00631L.TW": ("台灣50正2（測試）", 120.0, 2.0, "tw"),
    "6488.TWO": ("環球晶（測試）", 500.0, -1.0, "tw"),
    "2303.TW": ("聯電（測試）", 45.6, -1.72, "tw"),
    "2603.TW": ("長榮（測試）", 180.0, 0.84, "tw"),
    "0050.TW": ("台灣50（測試）", 100.25, 0.25, "tw"),
    "00878.TW": ("高股息（測試）", 25.3, -0.4, "tw"),
    "AAPL": ("Apple（測試）", 190.0, 0.53, "us"),
    "MSFT": ("Microsoft（測試）", 400.0, -0.5, "us"),
}


def quote(code):
    name, price, change_pct, _ = STOCKS[code]
    previous = round(price / (1 + change_pct / 100), 2)
    return {
        "stock_code": code, "stock_name": name, "current_price": price,
        "change": round(price - previous, 2), "change_percent": change_pct,
        "open": price - 2, "high": price + 5, "low": price - 4,
        "prev_close": previous, "volume": 12345678, "amount": 7410000000,
        "volume_ratio": 1.2, "average_price": price - 1,
        "limit_up": round(previous * 1.1, 2), "limit_down": round(previous * 0.9, 2),
        "best_bid": 0 if code == "2330.TW" else price - 1, "best_ask": price + 1,
        "best_bid_volume": 0 if code == "2330.TW" else 30, "best_ask_volume": 25,
        "source": "fixture（合成資料）", "as_of": AS_OF, "update_time": AS_OF,
        "is_stale": True,
    }


def bars(code):
    anchor = STOCKS[code][1]
    result = []
    # 約六年日線，讓 5Y 區間、月 K 與 MA60 都有東西可畫；價格從 anchor 的 55% 起漲並帶波動，維持正值。
    count = 2200
    for offset in range(count):
        trend = anchor * (0.55 + 0.45 * offset / (count - 1)) + anchor * 0.05 * math.sin(offset / 23)
        close = round(trend + ((offset % 5) - 4) * 0.5, 2)
        if offset == count - 2:
            close = quote(code)["prev_close"]
        result.append({
            "date": (date(2024, 1, 31) - timedelta(days=count - 1 - offset)).isoformat(),
            "open": close - 1 if offset % 2 else close + 1,
            "high": close + 3, "low": close - 3, "close": close,
            "volume": 1000000 + offset * 30000, "amount": close * 1000000,
        })
    latest = quote(code)
    result[-1].update(open=latest["open"], high=latest["high"], low=latest["low"],
                      close=latest["current_price"], volume=latest["volume"], amount=latest["amount"])
    if code == "MSFT":
        # 模擬日 K 來源缺當天、由報價補上的暫定 K（後端 `_with_provisional_bar`）。
        result[-1]["provisional"] = True
    return result


def intraday_source(code):
    return "fixture（合成分時）"


def intraday(code):
    """合成分時：台股 09:00～13:30（+08:00）、美股 09:30～16:00（-05:00），每 5 分鐘一點，收在報價現價。"""
    price, market = STOCKS[code][1], STOCKS[code][3]
    tz, start, minutes = ("+08:00", 9 * 60, 270) if market == "tw" else ("-05:00", 9 * 60 + 30, 390)
    day = "2024-01-31" if market == "tw" else "2024-01-30"
    count = minutes // 5 + 1
    points = []
    cum_value, cum_volume = 0.0, 0.0
    for index in range(count):
        minute = start + index * 5
        wave = math.sin(index / 9) * price * 0.006 + (index - count) * price * 0.00005
        point_price = round(price + wave if index < count - 1 else price, 2)
        volume = 200_000 + (index % 7) * 50_000
        cum_value += point_price * volume
        cum_volume += volume
        points.append({"t": f"{day}T{minute // 60:02d}:{minute % 60:02d}:00{tz}",
                       "price": point_price, "volume": volume,
                       "avg_price": round(cum_value / cum_volume, 4)})
    return points


def artifact(code, record_id=101):
    return {
        "schema_version": "research-artifact-v1", "artifact_id": f"fixture-{record_id}-{code}",
        "source_report_id": record_id, "source_query_id": f"fixture-query-{record_id}", "created_at": AS_OF,
        "subject": {"stock_code": code, "stock_name": STOCKS[code][0], "market": STOCKS[code][3]},
        "thesis": {
            "direction": "neutral", "summary": "【合成測試資料】營收與價格結構待確認，先觀察支撐，不追價。",
            "confidence": None, "score": 58, "horizon": "測試用觀察期間",
            "action": "watch", "action_label": "觀望（測試）",
            "reasons": ["測試營收年增改善", "測試日 K 支撐尚未失守"],
            "risks": ["測試估值偏高", "測試法人資料尚未更新"],
        },
        "evidence": [
            {"id": "fixture-revenue", "source_type": "fundamental", "title": "月營收（測試）",
             "summary": "合成資料用來驗證來源與日期顯示，不能用於投資。", "source": "fixture",
             "freshness": "stale", "quality_level": "limited", "as_of": AS_OF, "url": None},
            {"id": "fixture-price", "source_type": "technical", "title": "價格結構（測試）",
             "summary": "測試支撐附近仍需確認成交量。", "source": "fixture",
             "freshness": "stale", "quality_level": "limited", "as_of": AS_OF, "url": None},
        ],
        "invalidation_conditions": [
            {"id": "fixture-support", "category": "price", "description": "跌破測試支撐需重新判斷",
             "trigger": "測試日線收盤跌破支撐", "severity": "warning", "metric": "測試支撐價",
             "threshold": str(STOCKS[code][1] - 30), "due_at": None},
        ],
        "next_actions": [{"action": "watch", "label": "等待測試數據確認", "reason": "合成驗收資料，不是真實建議", "due_at": None}],
        "data_quality": {"level": "limited", "overall_score": None, "source_count": 2, "stale_count": 2,
                         "missing_blocks": ["institutional"], "limitations": ["全部為固定過去日期的合成 fixture，不能視為真行情或真 AI 分析。"]},
    }


def report_news(record_id):
    """#101 台積電與 #111 鴻海有混合資料；其餘報告模擬無新聞。"""
    if record_id not in (101, 111):
        return []
    return [
        {"title": "較早新聞（合成）", "snippet": "測試舊消息摘要", "url": "https://example.test/older",
         "source": "合成媒體", "published_date": "2024-01-29T08:00:00", "dimension": "latest_news"},
        {"title": "產業資料頁（合成）", "snippet": "| 欄位 | 數值 |\n| --- | --- |",
         "url": "https://example.test/industry", "source": "合成產業資料庫", "published_date": None, "dimension": "industry"},
        {"title": "最新新聞（合成）", "snippet": "**營收改善**，需求仍待確認。\n```json\n{\"raw_fixture_document\":true}\n```", "url": "https://example.test/latest",
         "source": "合成通訊社", "published_date": "2024-01-31T08:00:00.123456", "dimension": "latest_news"},
        {"title": "Document", "snippet": "EX-99.1 2 原始附件全文", "url": "https://www.sec.gov/Archives/fixture-8k.htm",
         "source": "SEC", "published_date": "2024-01-30T08:00:00", "dimension": "announcements"},
        {"title": "風險公告（無日期合成）", "snippet": "一般風險摘要", "url": "javascript:alert(1)",
         "source": "合成公告", "published_date": None, "dimension": "risk_check"},
        {"title": "財報資料頁（合成）", "snippet": "資料頁摘要", "url": "https://example.test/earnings",
         "source": "合成財報資料庫", "published_date": None, "dimension": "earnings"},
        {"title": "市場資料頁（合成）", "snippet": "資料頁摘要", "url": "https://example.test/market",
         "source": "合成市場資料庫", "published_date": None, "dimension": "market_analysis"},
    ]


def history_item(record_id, code, report_type="detailed", region=None):
    is_market = report_type == "market_review"
    return {
        "id": record_id, "query_id": f"fixture-query-{record_id}", "stock_code": code,
        "stock_name": "大盤觀察（測試）" if is_market else STOCKS[code][0],
        "report_type": report_type, "region": region, "trend_prediction": "觀察（測試）",
        "analysis_summary": "【合成測試資料】市場與個股等待確認；驗證 AI 摘要、風險與依據。",
        "sentiment_score": None if is_market else 58, "operation_advice": "觀望（測試）",
        "action": "watch", "action_label": "觀望（測試）",
        "current_price": None if is_market else STOCKS[code][1], "change_pct": None if is_market else STOCKS[code][2],
        "model_used": "fixture-only", "created_at": AS_OF, "asset_type": "index" if is_market else "stock",
    }


def financials_fixture(code):
    """合成財報：AI 已標記毛利率，其他欄位不標；所有數字都是假的。"""
    point = lambda period, value, yoy=None, pp=None: {
        "period": period, "value": value, "yoy_pct": yoy, "qoq_pct": None, "yoy_pp": pp, "qoq_pp": None, "derived": False}
    return {
        "stock_code": code, "market": "tw", "status": "ok", "status_reason": None, "stock_name": None,
        "template": "general", "currency": "TWD", "trading_currency": "TWD",
        "source": {"id": "fixture", "label": "合成測試財報", "source_unit": "新台幣千元", "url": None},
        "cross_check": None,
        "periods": [{"key": "2099Q2", "label": "2099 Q2", "fiscal_year": 2099, "fiscal_quarter": 2,
                     "period_end": "2099-06-30", "announce_date": "2099-08-14",
                     "announce_date_kind": "statutory_deadline", "filing_form": ""}],
        "metrics": [
            {"key": "revenue", "label": "營收", "kind": "amount", "unit": "TWD", "definition": "合成：營收教學",
             "points": [point("2099Q2", 1.27e12, yoy=36.0)]},
            {"key": "gross_margin", "label": "毛利率", "kind": "ratio", "unit": "%", "definition": "合成：毛利率教學",
             "points": [point("2099Q2", 67.7, pp=9.1)]},
        ],
        "not_applicable": [{"key": "contract_liabilities", "label": "合約負債", "reason": "合成：沒有揭露"}],
        "monthly_revenue": [{"month": "2099-09", "revenue": 5e11, "yoy_pct": 54.6, "mom_pct": -0.6, "announce_date": "2099-10-10"}],
        "ttm_revenue_yoy_pct": 36.2, "limitations": ["合成測試資料"], "is_stale": False,
        "commentary": {"status": "ready", "period": "2099Q2", "generated_at": None, "model": "fixture",
                       "headline": "合成導讀：毛利率大幅上升", "message": None,
                       "highlights": [{"metric_key": "gross_margin", "period": "2099Q2", "importance": "high",
                                       "what_happened": "合成：毛利率上升", "why_it_matters": "合成：定價能力變強",
                                       "how_to_read": "合成：毛利除以營收"}]},
    }


def calendar_events(query):
    """行事曆獨立使用相對日期，讓 7 天警示與換月驗收不會過期。"""
    # App 預設開裝置當天；fixture 與模擬器同機，用本機日期才不會在跨日時段對不上。
    today = datetime.now().date()
    eastern_day = datetime.now(ZoneInfo("America/New_York")).date()
    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    def event(identifier, kind, code, name, day, status, detail, zone="America/New_York", date_kind="release"):
        return {"id": identifier, "type": kind, "code": code, "name": name, "date": day.isoformat(),
                "status": status, "detail": detail, "source_url": "https://example.test/calendar-fixture",
                "timezone": zone, "date_kind": date_kind, "updated_at": datetime.now(timezone.utc).isoformat()}
    events = [
        event("fixture-aapl", "earnings", "AAPL", "Apple（測試）", today, "confirmed", "合成盤後財報 · EPS 預估 1.20"),
        event("fixture-aapl-next", "earnings", "AAPL", "Apple（測試）", next_month, "estimated", "合成推估財報，日期可能調整"),
        event("fixture-fomc", "fomc", None, "FOMC（合成測試）", today, "confirmed", "合成總經事件"),
        event("fixture-deadline", "financial_deadline", None, "台股財報法定期限（測試）", today, "confirmed",
              "合成財報法定期限；不代表實際發布日", "Asia/Taipei", "statutory_deadline"),
    ]
    # 個股頁查詢起點是美東今日；當 UTC 已隔日但美東仍前一天時，仍保留來源日期。
    if eastern_day != today:
        events.append(event("fixture-aapl-eastern", "earnings", "AAPL", "Apple（測試）", eastern_day,
                            "confirmed", "合成美東盤後財報"))
    start, end = query.get("from", [today.isoformat()])[0], query.get("to", [today.isoformat()])[0]
    code = query.get("code", [None])[0]
    events = [item for item in events if start <= item["date"] <= end and (code is None or item["code"] == code)]
    undated = [{"code": "MSFT", "name": "Microsoft（測試）", "detail": "來源尚未提供下次財報日期"}]
    if code is not None:
        undated = [item for item in undated if item["code"] == code]
    return {"events": events, "undated": undated, "cache_updated_at": datetime.now(timezone.utc).isoformat()}


class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.calendar_failing = False
        self.watchlist = ["2330.TW", "2317.TW", "00631L.TW", "2303.TW", "2603.TW", "0050.TW", "00878.TW", "AAPL"]
        self.records = [history_item(101, "2330.TW"), history_item(102, "AAPL"),
                        history_item(201, "TWII", "market_review", "tw"),
                        history_item(202, "SPX", "market_review", "us")]
        self.records += [history_item(110 + index, code) for index, code in enumerate(self.watchlist)
                         if code not in ("2330.TW", "AAPL")]
        self.tasks = {}
        self.analysis_starts = 0
        self.next_record_id = 301

    def report(self, item):
        code = item["stock_code"]
        is_market = item["report_type"] == "market_review"
        return {
            "meta": {key: item.get(key) for key in ["id", "query_id", "stock_code", "stock_name", "report_type", "created_at", "current_price", "change_pct", "model_used", "asset_type"]},
            "summary": {key: item.get(key) for key in ["analysis_summary", "operation_advice", "action", "action_label", "trend_prediction", "sentiment_score"]},
            "strategy": None if is_market else {"ideal_buy": "等待測試支撐確認", "secondary_buy": None,
                                                "stop_loss": "跌破測試支撐再評估", "take_profit": "測試壓力區分批觀察"},
            "structured_report": None if is_market else artifact(code, item["id"]),
        }


STATE = State()


class Handler(BaseHTTPRequestHandler):
    server_version = "DSAIOSFixture/1"
    access_required = False

    def access_headers_valid(self):
        return (self.headers.get("CF-Access-Client-Id") == "fixture-access-id"
                and self.headers.get("CF-Access-Client-Secret") == "fixture-access-secret")

    def access_cookie_valid(self):
        cookies = SimpleCookie()
        cookies.load(self.headers.get("Cookie", ""))
        return cookies.get("CF_Authorization") is not None and cookies["CF_Authorization"].value == "fixture-access-cookie"

    def check_access(self):
        if not self.access_required or self.access_headers_valid() or self.access_cookie_valid():
            return True
        self.reply(302, headers={"Location": "https://fixture.cloudflareaccess.com/cdn-cgi/access/login"})
        return False

    def log_message(self, format, *args):
        # 日誌只記方法、路徑與 HTTP 狀態，不記密碼、cookie 或請求內容。
        print("fixture " + format % args, flush=True)

    def reply(self, status, payload=None, headers=None, content_type="application/json; charset=utf-8"):
        content = b"" if payload is None else (json.dumps(payload, ensure_ascii=False).encode() if content_type.startswith("application/json") else payload.encode())
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-DSA-Fixture", "synthetic-data-only")
        if self.access_required and self.access_headers_valid():
            # loopback HTTP fixture 無 Secure；正式 HTTPS 回應的 Secure 屬性由原生 cookie jar 保留。
            self.send_header("Set-Cookie", "CF_Authorization=fixture-access-cookie; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if content:
            self.wfile.write(content)

    def authenticated(self):
        cookies = SimpleCookie()
        cookies.load(self.headers.get("Cookie", ""))
        return cookies.get("dsa_session") is not None and cookies["dsa_session"].value == FIXTURE_COOKIE

    def route(self):
        parsed = urlsplit(self.path)
        return [unquote(part) for part in parsed.path.strip("/").split("/")], parse_qs(parsed.query)

    def do_GET(self):
        if not self.check_access():
            return
        route, query = self.route()
        if self.access_required and route == ["access-cookie-proof.js"]:
            if not self.access_cookie_valid() or self.access_headers_valid():
                return self.reply(403, "", content_type="text/javascript")
            return self.reply(200, "document.getElementById('access-proof').textContent='Access 子資源 Cookie 已驗證';", content_type="text/javascript")
        if self.access_required and route == ["access-redirect"]:
            return self.reply(302, headers={"Location": "https://fixture.cloudflareaccess.com/cdn-cgi/access/login"})
        if route == ["api", "v1", "stocks", "quotes"] and QUOTE_DELAY:
            # 正式站報價常是 refresh 裡最慢的一支；延遲放在鎖外，重現下拉更新途中的取消。
            time.sleep(QUOTE_DELAY)
        with STATE.lock:
            if route == ["__fixture", "calendar-failing"]:
                # UI 測試注入行事曆失敗，驗證事件卡的失敗與恢復。
                STATE.calendar_failing = query.get("on", ["0"])[0] == "1"
                return self.reply(200, {"calendar_failing": STATE.calendar_failing})
            if route == ["health"]:
                return self.reply(200, {"status": "fixture", "synthetic": True})
            if route == ["api", "v1", "auth", "status"]:
                return self.reply(200, {"authEnabled": True, "loggedIn": self.authenticated(), "passwordSet": True,
                                        "passwordChangeable": False, "setupState": "enabled"})
            if route == ["stocks.index.json"]:
                items = [[code, code.removesuffix(".TW").removesuffix(".TWO"), values[0], None, None, [],
                          values[3].upper(), "etf" if code.startswith("00631") else "stock", True, 10]
                         for code, values in STOCKS.items()]
                return self.reply(200, items)
            if not self.authenticated():
                return self.reply(401, {"error": "unauthorized", "message": "請登入測試服務"})
            if route == ["api", "v1", "calendar", "events"]:
                if STATE.calendar_failing:
                    return self.reply(503, {"error": "fixture", "message": "合成行事曆失敗"})
                return self.reply(200, calendar_events(query))
            if route == ["api", "v1", "alerts", "monitor", "status"]:
                return self.reply(200, {
                    "enabled": True, "without_schedule": True, "running": True, "mode": "monitor_only",
                    "reason": None, "interval_seconds": 300, "last_run_at": "2026-11-01T09:00:00",
                    "last_finished_at": "2026-11-01T09:00:01", "next_run_at": None, "last_error": None,
                    "last_stats": {"evaluated": 2}, "channels": ["telegram"], "enabled_rules": 2,
                })
            if route == ["api", "v1", "stocks", "watchlist"]:
                return self.reply(200, {"stock_codes": STATE.watchlist, "message": "合成測試自選股"})
            if route == ["api", "v1", "stocks", "quotes"]:
                codes = query.get("codes", [""])[0].split(",")
                return self.reply(200, {"items": [{"stock_code": code, "quote": quote(code) if code in STOCKS else None,
                                                   "error": None if code in STOCKS else "no_data"} for code in codes]})
            if route == ["api", "v1", "stocks", "indices"]:
                region = query.get("region", ["tw"])[0]
                data = [("TWII", "加權指數（測試）", 18000, 100, 0.56), ("TPEX", "櫃買指數（測試）", 230, -1, -0.43)] if region == "tw" else [
                    ("SPX", "S&P 500（測試）", 4800, 20, 0.42), ("IXIC", "NASDAQ（測試）", 15000, -50, -0.33)]
                return self.reply(200, {"region": region, "items": [dict(zip(["code", "name", "current", "change", "change_pct"], row), source="fixture（合成資料）", as_of=AS_OF) for row in data]})
            if len(route) == 5 and route[:3] == ["api", "v1", "stocks"] and route[4] == "trend":
                code = route[3]
                if code not in STOCKS:
                    return self.reply(200, {"stock_code": code, "range": "day", "source": None, "points": []})
                if query.get("range", ["month"])[0] == "month":
                    time.sleep(DAILY_TREND_DELAY)
                    daily = [{"t": bar["date"], "price": bar["close"]} for bar in bars(code)[-30:]]
                    return self.reply(200, {"stock_code": code, "range": "month", "source": "fixture（合成日線）", "points": daily})
                return self.reply(200, {"stock_code": code, "range": "day", "source": intraday_source(code),
                                        "points": intraday(code)})
            if len(route) == 5 and route[:3] == ["api", "v1", "stocks"] and route[4] == "profile":
                code = route[3]
                if code not in STOCKS:
                    return self.reply(404, {"detail": {"error": "not_found", "message": "測試資料沒有此股票"}})
                records = [item for item in STATE.records if item["stock_code"] == code]
                return self.reply(200, {
                    "requested_code": code, "canonical_code": code, "market": STOCKS[code][3], "as_of": AS_OF,
                    "quote": {"status": "partial", "data": quote(code), "limitations": ["合成測試資料"]},
                    "history": {"status": "partial", "period": "daily", "data": bars(code), "limitations": ["合成測試 K 線"]},
                    "research": {"status": "partial", "data": {"latest_report": records[0] if records else None,
                                   "recent_reports": records, "structured_report": artifact(code, records[0]["id"] if records else 101)}, "limitations": ["合成測試分析"]},
                    "evidence_quality": {"status": "partial", "blocks": {"quote": "partial", "research": "partial"},
                                         "limitations": ["全部是固定過去日期的 fixture，不能用於交易。", "no_symbol_intelligence"]},
                })
            if len(route) == 5 and route[:3] == ["api", "v1", "stocks"] and route[4] == "financials":
                if route[3] not in STOCKS:
                    return self.reply(404, {"detail": {"error": "not_found", "message": "測試資料沒有此股票"}})
                return self.reply(200, financials_fixture(route[3]))
            if len(route) == 5 and route[:3] == ["api", "v1", "stocks"] and route[4] == "dossier":
                code = route[3]
                if code not in STOCKS:
                    return self.reply(404, {"detail": {"error": "not_found", "message": "查無測試股票"}})
                return self.reply(200, f"<!doctype html><html lang='zh-Hant'><meta name='viewport' content='width=device-width'><body style='background:#101824;color:#fff;font:18px system-ui;padding:24px'><h1>四維度合成檔案 {code}</h1><p>受登入保護的 {code} 測試研究檔案，不能視為真實研究。</p></body></html>", content_type="text/html; charset=utf-8")
            if route == ["api", "v1", "history"]:
                records = STATE.records
                for key in ["stock_code", "report_type"]:
                    if key in query:
                        records = [item for item in records if item.get(key) == query[key][0]]
                page = int(query.get("page", ["1"])[0])
                limit = int(query.get("limit", ["20"])[0])
                return self.reply(200, {"total": len(records), "page": page, "limit": limit,
                                        "items": records[(page - 1) * limit:page * limit]})
            if len(route) >= 4 and route[:3] == ["api", "v1", "history"]:
                record = next((item for item in STATE.records if str(item["id"]) == route[3]), None)
                if not record:
                    return self.reply(404, {"detail": {"error": "not_found", "message": "查無測試報告"}})
                if len(route) == 5 and route[4] == "news":
                    if query.get("analysis_only") != ["true"]:
                        return self.reply(400, {"detail": {"error": "analysis_only_required", "message": "必須指定本次分析"}})
                    items = report_news(record["id"])[:int(query.get("limit", ["20"])[0])]
                    return self.reply(200, {"total": len(items), "items": items})
                if len(route) == 5 and route[4] == "markdown":
                    return self.reply(200, {"content": "# 合成測試完整報告\n\n這不是即時行情，也不是模型實際生成結果。\n\n## 觀察重點\n\n- 驗證完整文字可閱讀。\n- 驗證來源與失效條件可追溯。\n\n## 風險\n\n固定過去日期的測試資料，不能用於投資決策。"})
                if len(route) == 4:
                    return self.reply(200, STATE.report(record))
            if len(route) == 5 and route[:4] == ["api", "v1", "analysis", "status"]:
                task = STATE.tasks.get(route[4])
                if not task:
                    return self.reply(404, {"detail": {"error": "not_found", "message": "查無測試任務"}})
                task["polls"] += 1
                complete = task["polls"] >= 3
                result = None
                if complete:
                    if not task.get("record"):
                        task["record"] = history_item(STATE.next_record_id, task["code"])
                        STATE.next_record_id += 1
                        STATE.records.insert(0, task["record"])
                    report = STATE.report(task["record"])
                    result = {"query_id": task["record"]["query_id"], "stock_code": task["code"],
                              "stock_name": STOCKS[task["code"]][0], "created_at": AS_OF, "report": report}
                return self.reply(200, {"task_id": route[4], "status": "completed" if complete else "processing",
                                       "progress": 100 if complete else task["polls"] * 30,
                                       "result": result, "error": None, "stock_name": STOCKS[task["code"]][0]})
            if route == ["api", "v1", "portfolio", "snapshot"]:
                return self.reply(200, portfolio())
            if route == [""] or (route and route[0] in ["chat", "screening", "portfolio", "alerts", "funds", "decision-signals", "backtest", "data", "settings", "usage"]):
                html = tool_html("/" + "/".join(route), query.get("embed", ["無"])[0])
                if self.access_required:
                    html = html.replace("</body>", "<p id='access-proof'>驗證 Access 子資源中</p><script src='/access-cookie-proof.js'></script><a href='/access-redirect'>測試 Access 失效轉址</a></body>")
                return self.reply(200, html, content_type="text/html; charset=utf-8")
            if route == ["api", "v1", "fixture", "export"]:
                return self.reply(200, {"fixture": True, "kind": "http-download", "as_of": AS_OF},
                                  headers={"Content-Disposition": 'attachment; filename="fixture-http-export.json"'})
            return self.reply(404, {"detail": {"error": "fixture_route_missing", "message": "此路徑尚未加入 fixture"}})

    def do_POST(self):
        if not self.check_access():
            return
        route, _ = self.route()
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        with STATE.lock:
            if route == ["api", "v1", "auth", "login"]:
                if body.get("password") != FIXTURE_PASSWORD:
                    return self.reply(401, {"error": "invalid_password", "message": "測試密碼錯誤"})
                return self.reply(200, {"ok": True}, {"Set-Cookie": f"dsa_session={FIXTURE_COOKIE}; Path=/; HttpOnly; SameSite=Lax"})
            if not self.authenticated():
                return self.reply(401, {"error": "unauthorized", "message": "請登入測試服務"})
            if route == ["api", "v1", "auth", "logout"]:
                return self.reply(204, headers={"Set-Cookie": "dsa_session=; Max-Age=0; Path=/; HttpOnly"})
            if len(route) == 5 and route[:4] == ["api", "v1", "stocks", "watchlist"]:
                code = body.get("stock_code")
                if code not in STOCKS:
                    return self.reply(400, {"detail": {"error": "invalid_stock_code", "message": "測試股票代碼無效"}})
                if route[4] == "add" and code not in STATE.watchlist:
                    STATE.watchlist.append(code)
                elif route[4] == "remove" and code in STATE.watchlist:
                    STATE.watchlist.remove(code)
                return self.reply(200, {"stock_codes": STATE.watchlist, "message": "已更新合成測試自選股"})
            if route == ["api", "v1", "analysis", "analyze"]:
                code = body.get("stock_code")
                if code not in STOCKS or body.get("async_mode") is not True or body.get("notify") is not False:
                    return self.reply(422, {"detail": {"error": "invalid_fixture_request", "message": "分析需使用有效測試代碼、async_mode=true、notify=false"}})
                STATE.analysis_starts += 1
                if STATE.analysis_starts == 1:
                    return self.reply(202, {"task_id": "expired-fixture-task", "status": "pending", "message": "模擬服務重啟後任務遺失", "analysis_phase": "auto"})
                task_id = f"fixture-task-{len(STATE.tasks) + 1}"
                STATE.tasks[task_id] = {"code": code, "polls": 0}
                return self.reply(202, {"task_id": task_id, "status": "pending", "message": "合成測試任務已排入", "analysis_phase": "auto"})
            return self.reply(404, {"detail": {"error": "fixture_route_missing", "message": "此路徑尚未加入 fixture"}})


def tool_html(route_path="/chat", embed="無"):
    return """<!doctype html><html lang="zh-Hant"><meta name="viewport" content="width=device-width">
<body style="background:#101824;color:#fff;font:18px system-ui;padding:24px">
<h1>進階工具（合成驗收頁）</h1><p>頁面路徑：{{ROUTE}}</p><p>內嵌模式：{{EMBED}}</p>
<p>此處只驗證登入 cookie、內嵌瀏覽器與本機匯出，不代表真實工具功能通過。</p>
<button id="fixture-blob-export" style="padding:16px;font:18px system-ui">匯出合成設定 JSON</button>
<p><a href="/api/v1/fixture/export" download="fixture-http-export.json" style="color:#80efcf">下載 HTTP 合成檔案</a></p>
<script>
document.getElementById('fixture-blob-export').addEventListener('click', () => {
  const blob = new Blob([JSON.stringify({fixture:true, kind:'blob-download', marker:'DSA-IOS-EXPORT-FIXTURE'})], {type:'application/json'});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'fixture-settings.json';
  document.body.appendChild(link);
  link.click();
  link.remove();
});
</script></body></html>""".replace("{{ROUTE}}", escape(route_path)).replace("{{EMBED}}", escape(embed))


def portfolio():
    limitations = ["realtime_quote_best_effort", "fx_and_cost_basis_partial", "sector_and_risk_metrics_limited"]
    position = {"symbol": "2330.TW", "name": STOCKS["2330.TW"][0], "market": "tw", "currency": "TWD",
                "quantity": 1000.0, "avg_cost": 580.0, "total_cost": 580000.0, "last_price": 600.0,
                "market_value_base": 600000.0, "unrealized_pnl_base": 20000.0, "unrealized_pnl_pct": 3.45,
                "valuation_currency": "TWD", "price_source": "realtime_quote", "price_provider": "shioaji",
                "price_date": "2024-01-31", "price_stale": False, "price_available": True,
                "data_quality": "partial", "limitations": limitations}
    account = {"account_id": 1, "account_name": "合成測試帳戶", "market": "tw", "base_currency": "TWD",
               "total_cash": 400000.0, "total_market_value": 600000.0, "total_equity": 1000000.0,
               "realized_pnl": 0.0, "unrealized_pnl": 20000.0, "data_quality": "partial",
               "fx_stale": False, "fx_missing": False, "limitations": limitations, "positions": [position]}
    second = deepcopy(account)
    second.update(account_id=2, account_name="第二台幣帳戶（測試）", total_cash=80000.0,
                  total_market_value=120000.0, total_equity=200000.0, unrealized_pnl=20000.0)
    second["positions"][0].update(symbol="00631L.TW", name=STOCKS["00631L.TW"][0],
                                  avg_cost=100.0, total_cost=100000.0, last_price=120.0,
                                  market_value_base=120000.0, unrealized_pnl_pct=20.0, price_stale=True)
    dollar = deepcopy(account)
    dollar.update(account_id=3, account_name="美元帳戶（測試）", market="us", base_currency="USD",
                  total_cash=4700.0, total_market_value=7800.0, total_equity=12500.0, unrealized_pnl=300.0)
    dollar["positions"][0].update(symbol="AAPL", name=STOCKS["AAPL"][0], market="us", currency="USD",
                                  quantity=20.0, avg_cost=180.0, total_cost=3600.0, last_price=190.0,
                                  market_value_base=3800.0, unrealized_pnl_base=200.0,
                                  unrealized_pnl_pct=5.56, valuation_currency="USD", price_provider="yfinance")
    microsoft = deepcopy(dollar["positions"][0])
    microsoft.update(symbol="MSFT", name=STOCKS["MSFT"][0], quantity=10.0, avg_cost=390.0,
                     total_cost=3900.0, last_price=400.0, market_value_base=4000.0,
                     unrealized_pnl_base=100.0, unrealized_pnl_pct=2.56, price_provider="fallback")
    dollar["positions"].append(microsoft)
    # 重現正式契約：頂層是跨幣別 CNY，原幣帳戶完整；CNY 換算缺漏不應污染台幣／美元分組。
    return {"as_of": "2024-01-31", "cost_method": "fifo", "currency": "CNY", "account_count": 3,
            "total_cash": 82345.67, "total_market_value": 200000.0, "total_equity": 282345.67,
            "realized_pnl": 0.0, "unrealized_pnl": 10000.0, "fx_stale": True, "fx_missing": True,
            "data_quality": "partial", "limitations": ["合成測試資料，不能視為實際帳戶餘額"] + limitations,
            "accounts": [account, second, dollar]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="0 由作業系統分配可用 port")
    parser.add_argument("--quote-delay", type=float, default=0, help="報價端點延遲秒數，重現慢報價")
    parser.add_argument("--daily-trend-delay", type=float, default=0,
                        help="/trend?range=month 延遲秒數，驗證分時不被日線拖住")
    parser.add_argument("--ready-file", type=Path, help="寫出 URL、port 與 PID，供驗收腳本傳入 UITest")
    args = parser.parse_args()
    global QUOTE_DELAY, DAILY_TREND_DELAY
    QUOTE_DELAY = args.quote_delay
    DAILY_TREND_DELAY = args.daily_trend_delay
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    class AccessHandler(Handler):
        access_required = True
    access_server = ThreadingHTTPServer(("127.0.0.1", 0), AccessHandler)
    threading.Thread(target=access_server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    import os
    ready = {"url": f"http://127.0.0.1:{port}", "access_url": f"http://127.0.0.1:{access_server.server_address[1]}",
             "port": port, "pid": os.getpid(), "fixture": True}
    if args.ready_file:
        args.ready_file.parent.mkdir(parents=True, exist_ok=True)
        args.ready_file.write_text(json.dumps(ready) + "\n", encoding="utf-8")
    print(json.dumps(ready), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        access_server.shutdown()
        access_server.server_close()


if __name__ == "__main__":
    main()
