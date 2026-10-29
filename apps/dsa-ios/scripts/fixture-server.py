#!/usr/bin/env python3
"""僅供 iOS 驗收的 loopback HTTP fixture；所有資料都是過去日期的合成測試資料。"""

import argparse
from copy import deepcopy
from datetime import date, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, unquote, urlsplit


AS_OF = "2024-01-31T13:30:00+08:00"
FIXTURE_PASSWORD = "fixture-password"
FIXTURE_COOKIE = "fixture-session-only"
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
    count = 190
    for offset in range(count):
        close = round(anchor - (count - 1 - offset) * 0.1 + ((offset % 5) - 4) * 0.5, 2)
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
    return result


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


class State:
    def __init__(self):
        self.lock = threading.RLock()
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
        route, query = self.route()
        with STATE.lock:
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
                                         "limitations": ["全部是固定過去日期的 fixture，不能用於交易。"]},
                })
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
                return self.reply(200, tool_html(), content_type="text/html; charset=utf-8")
            if route == ["api", "v1", "fixture", "export"]:
                return self.reply(200, {"fixture": True, "kind": "http-download", "as_of": AS_OF},
                                  headers={"Content-Disposition": 'attachment; filename="fixture-http-export.json"'})
            return self.reply(404, {"detail": {"error": "fixture_route_missing", "message": "此路徑尚未加入 fixture"}})

    def do_POST(self):
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


def tool_html():
    return """<!doctype html><html lang="zh-Hant"><meta name="viewport" content="width=device-width">
<body style="background:#101824;color:#fff;font:18px system-ui;padding:24px">
<h1>進階工具（合成驗收頁）</h1>
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
</script></body></html>"""


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
    parser.add_argument("--ready-file", type=Path, help="寫出 URL、port 與 PID，供驗收腳本傳入 UITest")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    port = server.server_address[1]
    import os
    ready = {"url": f"http://127.0.0.1:{port}", "port": port, "pid": os.getpid(), "fixture": True}
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


if __name__ == "__main__":
    main()
