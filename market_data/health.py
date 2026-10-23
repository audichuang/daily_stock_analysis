"""Data-completeness / freshness checks for the market schema.

Catches the silent-partial-crawl failure mode (a day with abnormally few rows,
e.g. one market missing) and stale tables.

    python -m market_data.health
"""

import argparse
import datetime
import statistics
from zoneinfo import ZoneInfo

from sqlalchemy import text

from market_data.adjust import ADJUSTMENT_WINDOW_DAYS
from market_data.closures import adhoc_closed_dates
from market_data.crawl import RECENT_SESSIONS, market_filter
from market_data.db import get_engine
from market_data.financial_statement import afterIFRS

_DATE_TABLES = ["price", "institutional", "margin", "monthly_revenue",
                "ex_dividend", "valuation", "market_index",
                "financial_statement"]
_DATE_COL = {"monthly_revenue": "revenue_month"}
_REQUIRED_TABLES = (
    "price", "institutional", "margin", "monthly_revenue", "ex_dividend",
    "valuation", "market_index")


_TAIPEI = ZoneInfo("Asia/Taipei")
# 收盤後官方日資料（TWSE/TPEx 行情、FMTQIK）要到這個時刻才算「應已發布」；
# 13:30 收盤到此之間跑 health 不該因為今天還沒入庫就擋。
SESSION_COMPLETE_AFTER = datetime.time(17, 0)
_SESSION_LOOKBACK_DAYS = 15


def _xtai_session_checker():
    """回傳 XTAI 的 ``is_session(date)``；exchange_calendars 不可用時回 None。

    日曆取不到時由呼叫端**跳過**檢查，不退回週一~五：退回去會把國定假日
    （颱風以外的已知休市日）誤判成缺資料而擋掉報告。"""
    try:
        import exchange_calendars as xcals

        calendar = xcals.get_calendar("XTAI")
    except Exception:
        return None
    # 颱風假等臨時休市日曆不知道，由 `market_data.closures` 的清單補上。
    closed = adhoc_closed_dates()
    return lambda day: bool(calendar.is_session(day)) and _as_date(day) not in closed


def expected_session(now=None, is_session=None):
    """此刻庫裡「應該已經有」的最近一個交易日；取不到日曆回 None。

    今天是交易日且已過 ``SESSION_COMPLETE_AFTER``（台北）→ 今天；否則往前找最近的
    交易日（上限 ``_SESSION_LOOKBACK_DAYS`` 天）。``now`` 無時區視為台北時間。
    ``is_session`` 為 ``date -> bool``，預設取 XTAI。函式名與簽名是
    `scripts/daily_report.sh` 的契約，勿改。"""
    now = now or datetime.datetime.now(_TAIPEI)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_TAIPEI)
    now = now.astimezone(_TAIPEI)
    is_session = is_session or _xtai_session_checker()
    if is_session is None:
        return None
    today = now.date()
    try:
        if is_session(today) and now.time() >= SESSION_COMPLETE_AFTER:
            return today
    except Exception:
        return None
    return session_before(today, is_session=is_session)


def _as_date(day):
    return day.date() if isinstance(day, datetime.datetime) else day


def sessions_after(day, n, is_session=None):
    """``day`` 之後（不含 ``day``）的第 ``n`` 個交易日；``n`` 須 ≥ 1。

    ``n=1`` 即「下一個交易日」。``day`` 本身是不是交易日不影響結果。日曆取不到、
    日曆拋例外（例如超出 exchange_calendars 的範圍）或往後
    ``_SESSION_LOOKBACK_DAYS * n`` 個曆日內湊不滿 ``n`` 個交易日都回 None——
    呼叫端要把 None 當「日曆不可用」處理，不要自己退回週一~五（理由同
    `_xtai_session_checker`）。``is_session`` 為 ``date -> bool``，預設取 XTAI。"""
    if n < 1:
        raise ValueError(f"n 必須 ≥ 1，收到 {n}")
    return _walk_sessions(day, 1, n, _SESSION_LOOKBACK_DAYS * n, is_session)


def session_before(day, is_session=None):
    """``day`` 之前（不含 ``day``）最近的一個交易日；取不到回 None（規則同 `sessions_after`）。"""
    return _walk_sessions(day, -1, 1, _SESSION_LOOKBACK_DAYS, is_session)


def _walk_sessions(day, step, n, limit, is_session):
    """從 ``day``（不含）往 ``step`` 方向逐日走最多 ``limit`` 個曆日，回第 ``n`` 個交易日。

    日曆取不到、日曆拋例外或走完仍湊不滿都回 None。"""
    is_session = is_session or _xtai_session_checker()
    if is_session is None:
        return None
    day = _as_date(day)
    found = 0
    try:
        for offset in range(1, limit + 1):
            candidate = day + datetime.timedelta(days=step * offset)
            if is_session(candidate):
                found += 1
                if found == n:
                    return candidate
    except Exception:
        return None
    return None


def missing_dates(reference, observed):
    """Return reference dates that have no rows in the observed source."""
    reference_keys = {str(value)[:10] for value in reference}
    observed_keys = {str(value)[:10] for value in observed}
    return sorted(reference_keys - observed_keys)


def _source_dates(conn, table, market, start):
    """``table`` 在 ``start`` 之後、指定市場（None = 上市）有資料的日期。"""
    return [row[0] for row in conn.execute(text(
        f"SELECT DISTINCT date FROM market.{table} WHERE date >= :start"
        + market_filter(table, market)), {"start": start, "market": market}).fetchall()]


def full_history_gaps(price_dates, table_dates, exclude_latest=True):
    """price 有、該表沒有的整日缺洞，**從該表首日起算**到 price 最新日。

    `missing_*_dates` 只看最近 ``RECENT_SESSIONS`` 個交易日，整天沒列且滑出窗口後
    就永久無聲（institutional 2026-01-22／01-30、margin 01-30 即如此）；這是全歷史
    的稽核清單，**只報不擋**——daily 修不到窗口外的日子，擋了只會讓人學會忽略 gate。

    - 該表首日之前的 price 日期不算（那是「還沒回補」，不是缺洞）。
    - ``exclude_latest``：扣掉 price 的最新一個交易日（法人／融資／估值都是 T+1，
      最新日尚未發布屬正常延遲）。
    - 該表完全沒有列 → 回 []（沒有首日可言，空表由 `empty required tables` 管）。"""
    price_keys = {str(value)[:10] for value in price_dates}
    table_keys = {str(value)[:10] for value in table_dates}
    if not price_keys or not table_keys:
        return []
    start = min(table_keys)
    end = max(price_keys)
    return sorted(day for day in price_keys - table_keys
                  if day >= start and not (exclude_latest and day == end))


def missing_adjustments(expected, stored):
    """Return valid ex-dividend keys that have no adjustment event."""
    def keys(rows):
        return {(str(stock_id), str(day)[:10]) for stock_id, day in rows}

    return sorted(keys(expected) - keys(stored))


def stale_financial_quarters(stored_dates, today):
    """已過公告截止日、但一列都沒有的財報季,回 ``(year, season, deadline)``。

    財報季更**不在 `daily` 裡**(見 `docs/market-data-pitfalls.md`),漏一季不會有任何
    東西喊——這裡是唯一會喊的地方。截止日對映直接用
    `financial_statement.afterIFRS`,不另抄一份日期表,避免兩份漂移。

    只檢查**涵蓋範圍之內**的季:早於庫內第一季的不報(那是「還沒回補」不是
    「停更」)、尚未到截止日的也不報。回傳的 ``season`` 是**會計期間**,Q4 的
    截止日在隔年 3/31——`financials --year 2019 --season 4` 寫進去的是
    `2020-03-31`,所以兩個都印出來,免得照著日期去猜參數猜錯年份。
    """
    stored = {str(value)[:10] for value in stored_dates}
    if not stored:
        return []
    first = min(stored)
    missing = []
    for year in range(int(first[:4]) - 1, today.year + 1):
        for season in (1, 2, 3, 4):
            deadline = str(afterIFRS(year, season).date())
            if deadline > str(today) or deadline < first:
                continue
            if deadline not in stored:
                missing.append((year, season, deadline))
    return missing


def recent_thin_days(thin_by_table, since):
    """只回傳 ``since`` 之後的 thin day。

    `thin_days` 掃全歷史，是稽核用的完整清單；但 strict gate 只能擋 `daily` 修得到的視窗。
    否則 2014 年的一個半日交易會讓 `make morning` 每天早上死在門口，而重跑 daily 永遠沒用。
    """
    if not since:
        return []
    cutoff = str(since)[:10]
    return sorted((table, day, rows)
                  for table, days in thin_by_table.items()
                  for day, rows in days if day >= cutoff)


def thin_days(day_counts, window=5, ratio=0.9):
    """單日列數低於「前後 ``window`` 個交易日局部中位數 × ratio」的日子。

    列數 = 掛牌檔數,日間穩定,0.9 抓得住單邊市場缺漏(TPEx 缺 ~42%、TWSE 缺
    ~58%)與截斷寫入。不能用全域中位數:16 年上市家數成長會讓舊年代整段誤報、
    近期缺漏漏報(TPEx 整邊缺時仍有 58% 列數,舊版 0.5 門檻抓不到)。"""
    thin = []
    for i, (d, n) in enumerate(day_counts):
        lo = max(0, i - window)
        neigh = [c for j, (_, c) in enumerate(day_counts[lo:i + window + 1], lo)
                 if j != i]
        if len(neigh) >= 3 and n < ratio * statistics.median(neigh):
            thin.append((str(d)[:10], n))
    return thin


# 全歷史整日缺洞／覆蓋率稽核的三張 T+1 表（只報不擋）。
_HISTORY_TABLES = ("institutional", "margin", "valuation")

_THIN_TABLES = ["price", "institutional", "margin"]  # 每日全市場列數穩定的表
_TPEX_THIN_TABLES = ["institutional", "margin", "valuation"]
# 三張籌碼表上市（market IS NULL）與上櫃（'tpex'）共表；既有的上市稽核只看上市列（過濾條件
# 用 crawl.market_filter）——否則上櫃回補到一半時，每日列數忽多忽少會被當成 thin day，
# 上櫃單邊有列也會掩蓋上市缺日。

# 已逐日與來源核對一致的合法稀疏日(補班日交易,法人/信用活動天然只剩一半):
# 不是資料缺漏,白名單排除避免每次稽核重複告警。新 thin day 先跑修復流程
# (backfill --force / 對源核對),確認合法才加進來。
_VERIFIED_THIN = {
    "institutional": {
        "2012-12-22", "2013-02-23", "2013-09-14", "2014-12-27", "2016-06-04",
        "2016-09-10", "2017-02-18", "2017-09-30", "2018-03-31", "2019-01-07",
    },
}


def report(engine=None, now=None, is_session=None):
    engine = engine or get_engine()
    out = {"tables": {}, "thin_days": {}, "thin_days_tpex": {}}
    with engine.connect() as c:
        for t in _DATE_TABLES:
            col = _DATE_COL.get(t, "date")
            row = c.execute(text(
                f"SELECT count(*), min({col}), max({col}) FROM market.{t}"
            )).fetchone()
            out["tables"][t] = {"rows": row[0], "start": str(row[1]),
                                "end": str(row[2])}
        for t in _THIN_TABLES:
            day_counts = c.execute(text(
                f"SELECT date, count(*) FROM market.{t} WHERE true{market_filter(t, None)} "
                f"GROUP BY date ORDER BY date")).fetchall()
            verified = _VERIFIED_THIN.get(t, set())
            out["thin_days"][t] = [(d, n) for d, n in thin_days(day_counts)
                                   if d not in verified]
        # 上櫃融資／估值不在 REVISED_SOURCES：第一次抓到半套就凍結，resume 也當它完成（只報不擋）
        for t in _TPEX_THIN_TABLES:
            day_counts = c.execute(text(
                f"SELECT date, count(*) FROM market.{t} WHERE true{market_filter(t, 'tpex')} "
                f"GROUP BY date ORDER BY date"), {"market": "tpex"}).fetchall()
            out["thin_days_tpex"][t] = thin_days(day_counts)

        # 視窗與 `crawl.daily_update` 的自動修復視窗**同一個常數**：檢查得比修復得遠，
        # gate 就會擋在一個 daily 補不到的缺口上，而錯誤訊息叫你重跑的正是 daily。
        recent_price_dates = [row[0] for row in c.execute(text(
            "SELECT DISTINCT date FROM market.price ORDER BY date DESC LIMIT :n"
        ), {"n": RECENT_SESSIONS}).fetchall()]
        recent_index_dates = []
        source_dates = {}
        if recent_price_dates:
            recent_index_dates = [row[0] for row in c.execute(text(
                "SELECT DISTINCT date FROM market.market_index "
                "WHERE index_id = 'TAIEX' AND date >= :start"
            ), {"start": min(recent_price_dates)}).fetchall()]

            for table in _HISTORY_TABLES:
                for key, market in ((table, None), (table + "_tpex", "tpex")):
                    source_dates[key] = _source_dates(c, table, market, min(recent_price_dates))
        else:
            source_dates = {k: [] for t in _HISTORY_TABLES for k in (t, t + "_tpex")}
        # 絕對新鮮度：上面兩個檢查只讓 price 與 TAIEX 互相比對，兩者同時缺今天
        # （同為 TWSE 來源、被封或盤中跑）時會一起通過；這裡對照日曆的「應有場次」。
        expected = expected_session(now, is_session)
        expected_check = None
        if expected is not None:
            has = {}
            for key, sql in (
                    ("price", "SELECT 1 FROM market.price WHERE date = :d LIMIT 1"),
                    ("taiex", "SELECT 1 FROM market.market_index "
                              "WHERE index_id = 'TAIEX' AND date = :d LIMIT 1")):
                has[key] = c.execute(text(sql), {"d": expected}).fetchone() is not None
            expected_check = {"date": str(expected), **has}
        # --- 只報不擋的全歷史稽核（不進 strict gate）---
        price_all = [row[0] for row in c.execute(text(
            "SELECT DISTINCT date FROM market.price ORDER BY date")).fetchall()]
        table_all = {t: [row[0] for row in c.execute(text(
            f"SELECT DISTINCT date FROM market.{t} WHERE true{market_filter(t, None)} ORDER BY date"
            )).fetchall()]
            for t in _HISTORY_TABLES}
        out["history_gaps"] = {t: full_history_gaps(price_all, table_all[t])
                               for t in _HISTORY_TABLES}
        # 覆蓋率：各表與 price 的「最新共同日期」上，stock_id 數 / price 的 stock_id 數。
        # 上市＋上櫃一起數（上櫃回補完成前，這個比例就是缺口的量化）。
        coverage = {}
        price_keys = {str(d)[:10]: d for d in price_all}
        for t in _HISTORY_TABLES:
            shared = sorted(price_keys.keys() & {str(d)[:10] for d in table_all[t]})
            if not shared:
                continue
            day = price_keys[shared[-1]]
            counts = []
            for table in (t, "price"):
                row = c.execute(text(
                    f"SELECT count(DISTINCT stock_id) FROM market.{table} "
                    "WHERE date = :d"), {"d": day}).fetchone()
                counts.append(int(row[0]) if row else 0)
            coverage[t] = {"date": shared[-1], "stocks": counts[0],
                           "price_stocks": counts[1]}
        out["coverage"] = coverage
        # 復權事件落在非交易日的筆數（讀取端已用 snap_events_to_sessions 移到下一
        # 交易日，表內日期不動）；只數 ≤ price 最新日的，未來的預告事件不算。
        adjustment_by_date = c.execute(text(
            "SELECT date, count(*) FROM market.price_adjustment GROUP BY date"
        )).fetchall()
        latest_price = max(price_keys) if price_keys else None
        out["offcalendar_adjustments"] = sum(
            int(n) for d, n in adjustment_by_date
            if latest_price and str(d)[:10] <= latest_price
            and str(d)[:10] not in price_keys)
        today = datetime.date.today()
        window =datetime.timedelta(days=ADJUSTMENT_WINDOW_DAYS)
        expected_adjustments = c.execute(text(
            "SELECT stock_id, date FROM market.ex_dividend "
            "WHERE close_before > 0 AND reference_price > 0 "
            "AND date BETWEEN :start AND :end"
        ), {"start": today - window, "end": today + window}).fetchall()
        stored_adjustments = c.execute(text(
            "SELECT stock_id, date FROM market.price_adjustment WHERE date >= :start"
        ), {"start": today - window}).fetchall()
        out["integrity"] = {
            # Price and TAIEX are independent official feeds; check both
            # directions so a stale calendar cannot certify another stale table.
            "missing_price_dates": missing_dates(
                recent_index_dates, recent_price_dates),
            "expected_session": expected_check,
            "missing_expected_session": (
                [expected_check["date"]]
                if expected_check and not (expected_check["price"]
                                           and expected_check["taiex"]) else []),
            "missing_index_dates": missing_dates(
                recent_price_dates, recent_index_dates),
            # 法人／融資是 T+1 資料；最新一個 price 交易日尚未發布屬正常延遲。
            "missing_institutional_dates": missing_dates(
                recent_price_dates[1:], source_dates["institutional"]),
            "missing_margin_dates": missing_dates(
                recent_price_dates[1:], source_dates["margin"]),
            # 估值走 BWIBBU_d，18:00 當天多半未發布，同樣容忍最新一日；
            # 更早的缺日 daily 會補，補不到（被封）才擋。
            "missing_valuation_dates": missing_dates(
                recent_price_dates[1:], source_dates["valuation"]),
            # 上櫃三表只報不擋（不進 strict gate）：TPEx 單邊失敗不該擋住每日報告。
            "missing_tpex_dates": {
                t: missing_dates(recent_price_dates[1:], source_dates[t + "_tpex"])
                for t in _HISTORY_TABLES},
            "missing_price_adjustments": missing_adjustments(
                expected_adjustments, stored_adjustments),
            # 全歷史 thin day 留在 out["thin_days"] 供稽核；strict 只擋這一段。
            "thin_recent_days": recent_thin_days(
                out["thin_days"],
                min(recent_price_dates) if recent_price_dates else None),
            # 只報不擋:財報要手動跑 `financials`(整季 IFRS html 包 1-2 GB),
            # 擋住 `make morning` 只會讓人學會忽略 gate。
            "stale_financial_quarters": stale_financial_quarters(
                [row[0] for row in c.execute(text(
                    "SELECT DISTINCT date FROM market.financial_statement"
                )).fetchall()], today),
        }
    return out


def fund_nav_status(engine=None):
    """境內基金淨值新鮮度（只報不擋）：最新淨值日、該日有幾檔、總列數；表不存在或查詢失敗回 None。

    公會每日檔一份混多個淨值日，所以看「最新日有幾檔」比只看最新日更能看出是不是停更。"""
    try:
        with (engine or get_engine()).connect() as conn:
            row = conn.execute(text(
                "SELECT max(date), count(*) FROM market.fund_nav")).fetchone()
            latest = row[0]
            funds = conn.execute(text(
                "SELECT count(*) FROM market.fund_nav WHERE date = :d"), {"d": latest}).scalar() if latest else 0
    except Exception:
        return None
    return {"latest": latest, "funds_on_latest": funds, "rows": row[1]}


def run(engine=None, strict=False, now=None, is_session=None):
    """Print the report and return a process exit code."""
    result = report(engine, now=now, is_session=is_session)
    for table, info in result["tables"].items():
        print(f"{table:16} {info['rows']:>10,}  {info['start'][:10]}~{info['end'][:10]}")
    for table, days in result["thin_days"].items():
        print(f"thin {table} days: {len(days)} -> {days[:10]}")
    for table, days in result.get("thin_days_tpex", {}).items():
        print(f"thin {table}_tpex days (只報不擋): {len(days)} -> {days[:10]}")
    integrity = result.get("integrity", {})
    latest_price = result.get("tables", {}).get("price", {}).get("end", "n/a")
    print(f"latest price session: {str(latest_price)[:10]}")
    expected_check = integrity.get("expected_session")
    if expected_check:
        mark = {True: "\u2713", False: "\u2717"}
        print(f"expected session: {expected_check['date']} "
              f"(price {mark[expected_check['price']]}, "
              f"TAIEX {mark[expected_check['taiex']]})")
    else:
        print("expected session check skipped (exchange_calendars unavailable)")
    missing_expected = integrity.get("missing_expected_session", [])
    missing_price = integrity.get("missing_price_dates", [])
    missing_index = integrity.get("missing_index_dates", [])
    missing_institutional = integrity.get("missing_institutional_dates", [])
    missing_margin = integrity.get("missing_margin_dates", [])
    missing_valuation = integrity.get("missing_valuation_dates", [])
    missing_events = integrity.get("missing_price_adjustments", [])
    print(f"missing price dates: {len(missing_price)} -> {missing_price[:10]}")
    print(f"missing TAIEX dates: {len(missing_index)} -> {missing_index[:10]}")
    print("missing institutional dates: "
          f"{len(missing_institutional)} -> {missing_institutional[:10]}")
    print(f"missing margin dates: {len(missing_margin)} -> {missing_margin[:10]}")
    print("missing valuation dates: "
          f"{len(missing_valuation)} -> {missing_valuation[:10]}")
    print(f"missing price adjustments: {len(missing_events)} -> {missing_events[:10]}")
    for table, days in integrity.get("missing_tpex_dates", {}).items():
        print(f"missing {table}_tpex dates (只報不擋): {len(days)} -> {days[:10]}")
    empty_required = [table for table in _REQUIRED_TABLES
                      if not result.get("tables", {}).get(table, {}).get("rows")]
    print(f"empty required tables: {len(empty_required)} -> {empty_required}")
    # strict 只擋 daily 修得到的近期視窗；全歷史 thin day 上面已印出來供稽核。
    thin_recent = integrity.get("thin_recent_days", [])
    print(f"thin days inside the daily window: {len(thin_recent)} -> {thin_recent[:10]}")
    stale_financials = integrity.get("stale_financial_quarters", [])
    print(f"stale financial quarters: {len(stale_financials)} -> "
          + ", ".join(f"{y}Q{s} (date {d})" for y, s, d in stale_financials[:10]))
    for year, season, _ in stale_financials[:10]:
        print("  repair: uv run --env-file .env python -m market_data.cli "
              f"financials --year {year} --season {season}")
    # 以下三組只報不擋，刻意不進下面的 gaps：daily 修不到窗口外的日子；全歷史缺洞只看上市。
    history_gaps = result.get("history_gaps", {})
    for table in _HISTORY_TABLES:
        days = history_gaps.get(table, [])
        # 列**最近** 10 筆：缺洞清單由舊到新，取前 10 會被 2012 年的老缺洞佔滿，
        # 而最近的（2026-01-22／01-30）才是 backfill 補得回、也最影響現在的。
        shown = days[-10:]
        print(f"full-history gaps {table}: {len(days)} (latest {len(shown)}) -> {shown}")
        for day in shown:
            print(f"  repair: uv run --env-file .env python -m market_data.cli "
                  f"backfill {table} --start {day} --end {day} --delay 3")
    coverage = result.get("coverage", {})
    if coverage:
        print("coverage vs price (latest shared date; "
              "上市＋上櫃; institutional 上櫃自 2018-01-15 起): "
              + ", ".join(f"{t} {info['stocks']}/{info['price_stocks']} "
                          f"({info['date']})" for t, info in coverage.items()))
    offcalendar = result.get("offcalendar_adjustments")
    if offcalendar is not None:
        print(f"price_adjustment events on non-session dates: {offcalendar} "
              "(約 242 筆屬預期且永久，讀取端已移到下一交易日，不要刪列)")
    fund = fund_nav_status(engine)
    if fund is not None:
        print(f"fund_nav latest {fund['latest']} ({fund['funds_on_latest']:,} funds), "
              f"{fund['rows']:,} rows (只報不擋)")
    gaps = (missing_expected, missing_price, missing_index, missing_institutional,
            missing_margin, missing_valuation, missing_events, thin_recent, empty_required)
    failed = any(gaps)
    if strict and failed:
        if missing_expected:
            print(f"應有場次 {missing_expected[0]} 尚未入庫（交易所未發布或被封）；"
                  "發布後重跑 daily。颱風等臨時休市日日曆不知道，也會停在這裡")
        print("repair: uv run --env-file .env python -m market_data.cli daily")
        print("verify: uv run --env-file .env python -m market_data.cli "
              "health --strict")
        print("long gaps require an explicit market_data.cli backfill date range; "
              "the daily command intentionally refuses unbounded recovery")
    return int(strict and failed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="return non-zero for thin, empty, or recent integrity gaps")
    args = parser.parse_args(argv)
    return run(strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
