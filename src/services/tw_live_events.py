"""台股個股 prompt 的「即時風險／事件」區塊：處置股／注意股與未來 N 個交易日的法說會、除權息。

抓取與新鮮度判準全在 `market_data/risk_flags.py`、`market_data/events.py`（比對回應自帶的日期，
證明不了就整份記不可用）；這裡只負責：

- 只在分析日 ≥ `health.expected_session()` 時抓（盤中分析日會晚於預期場次）：兩份都是「當前快照」，
  接到歷史分析日是錯的。
- 全市場名單每個基準日只抓一次（加鎖，避免並行分析同時打官方端點被擋）；失敗或有名單不可用時 30 分鐘後重抓。
- 三態用字：命中＝是；該市場名單都可用且新鮮才寫「否」；其餘一律「未確認，不代表沒有」。

任何失敗都回 None／''（fail-open），不擋報告。
"""

import logging
import threading
import time
from datetime import date, datetime
from typing import Any, Dict, Optional

from src.services.market_symbol_utils import split_suffix_symbol
from src.services.tw_backtest_context import _tr

logger = logging.getLogger(__name__)

EVENT_DAYS = 10  # 事件窗口：基準日之後第 1～第 10 個交易日
_SUFFIX_MARKET = {"TW": "twse", "TWO": "tpex"}
_LOCK = threading.Lock()


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


_RETRY_SECONDS = 30 * 60   # 抓取失敗或有名單不可用時，過這麼久才重抓；名單全部可用的結果整個基準日沿用
_cache: Dict[str, tuple] = {}     # as_of_iso -> (monotonic, 名單是否全部可用, 結果)


def _fetch_cached(as_of_iso: str) -> Optional[Dict[str, Any]]:
    """同一基準日不再每檔重打一次。失敗與不完整的結果只沿用 30 分鐘：長駐的 Web 服務第一次逾時或
    名單晚出時，不會整個交易日都缺這段或寫「未確認」。"""
    hit = _cache.get(as_of_iso)
    if hit and (hit[1] or time.monotonic() - hit[0] < _RETRY_SECONDS):
        return hit[2]
    live = _fetch(as_of_iso)
    # 處置／注意名單或事件來源（除權息、法說會）有任一份這輪不可用，就只沿用 30 分鐘
    complete = bool(live) and not any(live["risk_down"].values()) and not live.get("event_down")
    if as_of_iso not in _cache and len(_cache) >= 4:
        _cache.pop(next(iter(_cache)))
    _cache[as_of_iso] = (time.monotonic(), complete, live)
    return live


_fetch_cached.cache_clear = _cache.clear


def _fetch(as_of_iso: str) -> Optional[Dict[str, Any]]:
    try:
        from market_data import events, risk_flags
        from market_data.health import session_before, sessions_after

        as_of = date.fromisoformat(as_of_iso)
        nxt, end, prev = sessions_after(as_of, 1), sessions_after(as_of, EVENT_DAYS), session_before(as_of)
        if nxt is None or end is None or prev is None:
            return None
        flags, risk_statuses = risk_flags.fetch_risk_flags(as_of, nxt)
        window = events.EventWindow(nxt, end, prev, EVENT_DAYS)
        by_stock, event_statuses = events.upcoming(window)
        return {
            "as_of": as_of, "next": nxt, "window": window,
            "flags": flags, "risk_checked": risk_flags.checked_markets(risk_statuses),
            # 依市場分開：上市股「未確認」的原因不該列出上櫃名單
            "risk_down": {m: [s.name for s in risk_statuses if not s.ok and risk_flags.SOURCE_MARKET.get(s.name) == m]
                          for m in _SUFFIX_MARKET.values()},
            "by_stock": by_stock, "event_checked": events.checked_categories(event_statuses),
            "event_down": [st.name for st in event_statuses if not st.ok],
            "revenue_deadlines": events.revenue_deadlines(window),
        }
    except Exception as exc:  # noqa: BLE001 - prompt enrichment is strictly fail-open
        logger.warning("[tw-live-events] fail-open: %s", exc)
        return None


def load_tw_live_events(analysis_date: Any) -> Optional[Dict[str, Any]]:
    """分析日不是預期場次（歷史分析、DB 未更新、日曆不可用）回 None，不抓。"""
    try:
        from market_data.health import expected_session

        expected = expected_session()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[tw-live-events] fail-open: %s", exc)
        return None
    day = _as_date(analysis_date)
    if expected is None or day is None or day < expected:
        # 盤中分析日是今天、預期場次仍是昨天（17:00 才翻），所以只擋「早於」
        return None
    with _LOCK:
        return _fetch_cached(expected.isoformat())


def format_tw_live_block(live: Optional[Dict[str, Any]], code: str, language: str) -> str:
    if not live:
        return ""
    parts = split_suffix_symbol(str(code or "").strip().upper())
    if parts is None or parts[1] not in _SUFFIX_MARKET:
        return ""
    bare, market = parts[0], _SUFFIX_MARKET[parts[1]]
    T = _tr(language)
    nxt = live["next"].isoformat()

    hit = live["flags"].get(bare)
    if hit:
        risk = T(f"是（{hit.detail}）", f"是（{hit.detail}）", f"YES ({hit.detail})")
    elif market in live["risk_checked"]:
        risk = T("否（處置＋注意名單皆已查）", "否（处置＋注意名单皆已查）",
                 "No (both disposition and attention lists checked)")
    else:
        down = "、".join(live["risk_down"].get(market, [])) or "—"
        risk = T(f"未確認（名單不可用：{down}），不代表不是", f"未确认（名单不可用：{down}），不代表不是",
                 f"Unconfirmed (lists unavailable: {down}); this does not mean no")

    found = live["by_stock"].get(bare, [])
    labels = "、".join(e.label() for e in found)
    checked = live["event_checked"].get(market, [])
    if labels:
        ev = labels
    elif checked:
        ev = T(f"無（已查：{'、'.join(checked)}）", f"无（已查：{'、'.join(checked)}）",
               f"None (checked: {', '.join(checked)})")
    else:
        ev = T("未列", "未列", "None listed")
    unchecked = T("法說會僅列已申報者，未列不代表沒有", "法说会仅列已申报者，未列不代表没有",
                  "earnings calls list only filed ones; absence does not mean none")
    w = live["window"]
    lines = [
        T(f"\n### 處置／注意股與事件日曆（官方即時名單，基準日 {live['as_of']}）",
          f"\n### 处置／注意股与事件日历（官方即时名单，基准日 {live['as_of']}）",
          f"\n### Disposition / Attention Stocks and Event Calendar (official live lists, as of {live['as_of']})"),
        T(f"- 處置／注意股（下一交易日 {nxt}）：{risk}", f"- 处置／注意股（下一交易日 {nxt}）：{risk}",
          f"- Disposition / attention stock (next session {nxt}): {risk}"),
        T(f"- 近 {w.n} 交易日事件（{w.start}～{w.end}）：{ev}（{unchecked}）",
          f"- 近 {w.n} 交易日事件（{w.start}～{w.end}）：{ev}（{unchecked}）",
          f"- Events in the next {w.n} sessions ({w.start} to {w.end}): {ev} ({unchecked})"),
    ]
    if live["revenue_deadlines"]:
        days = "、".join(d.isoformat() for d in live["revenue_deadlines"])
        lines.append(T(f"- 月營收法定公告期限：{days}（全市場一致）", f"- 月营收法定公告期限：{days}（全市场一致）",
                       f"- Monthly revenue legal filing deadline: {days} (market-wide)"))
    lines.append(T(
        "> 處置股採分盤撮合（約 5～20 分鐘撮合一次，常需預收款券），流動性差、進出場價格難控制，"
        "若為處置中或即將處置，必須列為首要風險，不得給出積極買入結論；注意股代表近期異常波動。"
        "未來 2～3 個交易日內的法說會是催化劑也是風險（結果公布前後波動放大）；除權息日參考價會下調，"
        "目標價與停損要依除權息後的參考價對齊。「未確認」或「未列」時不得推論為沒有。",
        "> 处置股采分盘撮合（约 5～20 分钟撮合一次，常需预收款券），流动性差、进出场价格难控制，"
        "若为处置中或即将处置，必须列为首要风险，不得给出积极买入结论；注意股代表近期异常波动。"
        "未来 2～3 个交易日内的法说会是催化剂也是风险（结果公布前后波动放大）；除权息日参考价会下调，"
        "目标价与止损要依除权息后的参考价对齐。“未确认”或“未列”时不得推论为没有。",
        "> Disposition stocks trade by periodic call auction (one match every ~5-20 minutes, often with "
        "pre-paid cash/shares): liquidity is poor and fills are hard to control. If disposing or about to be, "
        "list it as the primary risk and do not give an aggressive buy. Attention stocks had abnormal recent "
        "moves. An earnings call within the next 2-3 sessions is both a catalyst and a risk; on an ex-dividend "
        "day the reference price drops, so align target and stop with the post-ex price. 'Unconfirmed' or "
        "'none listed' must not be read as 'none'.",
    ))
    return "\n".join(lines) + "\n"
