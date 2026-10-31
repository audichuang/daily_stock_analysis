"""持股＋自選行事曆：開頁／分析唯讀，排程才向外部刷新。"""
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.config import get_config
from src.repositories.calendar_repo import CalendarRepository
from src.services.calendar_sources import fetch_earnings
from src.services.market_symbol_utils import is_tw_suffix_symbol
from src.services.stock_list_parser import ParseStatus, parse_analysis_target

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
LAW_URL = "https://twse-regulation.twse.com.tw/TW/law/DOC01.aspx?FLCODE=FL007009&FLNO=36"
# 人工表只列已查核年份；超出範圍不外推。2027 官網仍為暫定。
VERIFIED_ON = "2026-11-01"
FOMC_DATES = {
    "2026-01-28": "confirmed", "2026-03-18": "confirmed", "2026-04-29": "confirmed",
    "2026-06-17": "confirmed", "2026-07-29": "confirmed", "2026-09-16": "confirmed",
    "2026-10-28": "confirmed", "2026-12-09": "confirmed",
    **{d: "estimated" for d in ("2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
                                "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08")},
}
CACHE_MAX_AGE = timedelta(days=3)


def canonical_code(raw):
    from data_provider.us_index_mapping import is_us_stock_code, is_us_index_code

    target = parse_analysis_target(raw)
    if target.asset_type != ParseStatus.STOCK:
        return None
    if is_tw_suffix_symbol(target.canonical_id):
        return target.canonical_id
    if target.exchange == "US" and is_us_stock_code(target.canonical_id) and not is_us_index_code(target.canonical_id):
        return target.canonical_id.replace("-", ".")
    return None


def calendar_members(config=None, db=None):
    """沿用自選設定與帳本重播；不取即時價、不存部位／快照。"""
    from src.services.portfolio_service import PortfolioService
    from src.repositories.portfolio_repo import PortfolioRepository
    from src.services.system_config_service import SystemConfigService
    from src.services.stock_list_parser import split_stock_list
    from src.data.stock_index_loader import get_index_stock_name

    config = config or get_config()
    # 跟 watchlist API 同樣讀已持久化設定，避免程序啟動時的 STOCK_LIST 快照。
    values = SystemConfigService().get_config(include_schema=False)
    raw = next((i.get("value", "") for i in values.get("items", []) if i.get("key") == "STOCK_LIST"), "")
    result = {}
    for raw_code in split_stock_list(str(raw)):
        code = canonical_code(raw_code)
        if code:
            result[code] = get_index_stock_name(code) or code
    snapshot = PortfolioService(repo=PortfolioRepository(db)).get_portfolio_snapshot(
        include_realtime=False, read_only=True)
    for account in snapshot.get("accounts", []):
        for position in account.get("positions", []):
            if position.get("quantity", 0) > 0:
                code = canonical_code(position["symbol"])
                if code:
                    result[code] = position.get("name") or result.get(code) or code
    return result


def _event(kind, day, name, detail, source, *, status="confirmed", tz="America/New_York", date_kind="release"):
    return {"id": f"{kind}:{day}", "type": kind, "code": None, "name": name,
            "date": day if isinstance(day, date) else date.fromisoformat(day), "status": status,
            "detail": detail, "source_url": source, "timezone": tz, "date_kind": date_kind,
            "updated_at": datetime.fromisoformat(VERIFIED_ON)}


def local_events(start, end, include_tw):
    rows = [_event("fomc", day, "FOMC 利率決議",
                   "14:00 ET 公布聲明；人工表查核 " + VERIFIED_ON
                   + ("；官方暫定日程" if status == "estimated" else ""), FOMC_URL, status=status)
            for day, status in FOMC_DATES.items() if start.isoformat() <= day <= end.isoformat()]
    if not include_tw:
        return rows
    note = ("法定期限，一般曆年制公司節點，非個股實際發布日；假日、金融業及核准展延另有例外。"
            "資本額達百億元上市櫃年度75日、第一上市櫃Q2兩個月；2026起保險業及具保險子公司月營收得延至15日。"
            "規則查核 " + VERIFIED_ON)
    for year in range(start.year - 1, end.year + 1):
        for month in range(1, 13):
            day = date(year, month, 10)
            if start <= day <= end:
                rows.append(_event("revenue_deadline", day, "台股月營收一般法定期限", note, LAW_URL,
                                   tz="Asia/Taipei", date_kind="statutory_deadline"))
        deadlines = [date(year, 3, 31)] + [
            date(year, m, d) + timedelta(days=45) for m, d in ((3, 31), (6, 30), (9, 30))
        ]
        for day in deadlines:
            if start <= day <= end:
                rows.append(_event("financial_deadline", day, "台股財報一般法定期限", note, LAW_URL,
                                   tz="Asia/Taipei", date_kind="statutory_deadline"))
    return rows


class CalendarService:
    def __init__(self, repo=None, members_provider=None):
        self.repo = repo or CalendarRepository()
        self.members_provider = members_provider or calendar_members

    def events(self, start, end, code=None, now=None):
        now = now or datetime.now(timezone.utc)
        naive_now = now.astimezone(timezone.utc).replace(tzinfo=None)
        members = self.members_provider()
        filter_by_code = code is not None
        if filter_by_code:
            code = canonical_code(code)
            members = {code: members[code]} if code in members else {}
        cached = self.repo.read(members, start, end)
        # 個股頁只回該股；全行事曆則合併人工表，未開刷新也能讀取。
        local = [] if filter_by_code else local_events(start, end, any(is_tw_suffix_symbol(c) for c in members))
        selected = {r["id"]: r for r in local}
        updated = []
        for row in cached:
            if filter_by_code and row["code"] is None:
                continue
            updated.append(row["updated_at"])
            if naive_now - row["updated_at"] > CACHE_MAX_AGE:
                continue
            if row["date"] is not None:
                selected[row["id"]] = row
        undated = []
        # 只讀期間內事件不足以判斷「未定」：另外讀所有未來日期，避免下個月才發報被誤標未定。
        future = self.repo.read(members, now.astimezone(ET).date(), date.max)
        dated_codes = {r["code"] for r in future if r["code"] and r["date"]
                       and r["date"] >= now.astimezone(ZoneInfo(r["timezone"])).date()
                       and naive_now - r["updated_at"] <= CACHE_MAX_AGE}
        for symbol, name in members.items():
            if symbol not in dated_codes:
                undated.append({"code": symbol, "name": name,
                                "detail": "下次財報日期未定（來源未提供、尚未更新或快取已過期）"})
        events = sorted(selected.values(), key=lambda r: (r["date"], r["id"]))
        return {"events": events, "undated": undated,
                "cache_updated_at": max(updated).isoformat() + "Z" if updated else None}

    def next_earnings(self, code, now=None):
        now = now or datetime.now(timezone.utc)
        code = canonical_code(code)
        if not code:
            return None
        day = now.astimezone(ZoneInfo("Asia/Taipei") if is_tw_suffix_symbol(code) else ET).date()
        rows = self.repo.read([code], day, date.max)
        fresh = [r for r in rows if r["code"] == code and r["type"] == "earnings" and r["date"]
                 and now.astimezone(timezone.utc).replace(tzinfo=None) - r["updated_at"] <= CACHE_MAX_AGE]
        return min(fresh, key=lambda r: r["date"]) if fresh else None

    def refresh(self, now=None):
        now = now or datetime.now(timezone.utc)
        members = self.members_provider()
        stats = {"updated": 0, "undated": 0, "failed": 0}
        for code, name in members.items():
            if is_tw_suffix_symbol(code):
                continue
            try:
                got = fetch_earnings(code, now.astimezone(ET).date())
                row = {"id": f"earnings:{code}", "type": "earnings", "code": code, "name": name[:128],
                       "date": None, "status": "estimated", "detail": "日期未定", "source_url": "",
                       "timezone": "America/New_York", "date_kind": "release",
                       "updated_at": now.astimezone(timezone.utc).replace(tzinfo=None)}
                if got:
                    row.update(got)
                    row["source_url"] = row["source_url"][:1024]
                self.repo.save_earnings(row)
                stats["updated" if got else "undated"] += 1
            except Exception as exc:
                stats["failed"] += 1
                logger.warning("財報快取更新失敗 %s: %s", code, type(exc).__name__)
        self._refresh_macro(now)
        return stats

    def _refresh_macro(self, now):
        from market_data import macro

        stamp = now.astimezone(timezone.utc).replace(tzinfo=None)
        try:
            dates = macro.parse_fed_calendar(macro.http_get(FOMC_URL).text)
            if not dates:
                raise ValueError("FOMC 官網沒有可解析的日期")
            rows = [_event("fomc", d, "FOMC 利率決議", "14:00 ET；官方日程（遠期暫定）", FOMC_URL,
                           status=FOMC_DATES.get(d.isoformat(), "estimated")) for d in dates]
            self.repo.replace_macro_type("fomc", [{**r, "updated_at": stamp} for r in rows])
        except Exception as exc:
            logger.warning("FOMC 快取更新失敗: %s", type(exc).__name__)
        try:
            rows = macro.collect_release_events(now.astimezone(ET).date(), now=now, out=logger.warning)
            by_type = {}
            for row in rows:
                source = row["source"]
                kind = row["event_type"]
                url = (macro.FRED_CALENDAR_URL.format(rid=macro.RELEASES["nfp" if kind == "unrate" else kind][0],
                                                      year=row["event_date"].year)
                       if source == "fred" else {"bea": macro.BEA_ICS_URL, "census": macro.CENSUS_CALENDAR_URL,
                                                 "cbc": "https://www.cbc.gov.tw/tw/cp-302-189514-82841-1.html",
                                                 "rule": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/"}.get(source, ""))
                event = _event(kind, row["event_date"], row["title"], row.get("time_note") or "", url,
                               status=row["status"], tz="Asia/Taipei" if kind == "cbc" else "America/New_York")
                by_type.setdefault(kind, []).append({**event, "updated_at": stamp})
            for kind, entries in by_type.items():
                self.repo.replace_macro_type(kind, entries)
        except Exception as exc:
            logger.warning("總經快取更新失敗: %s", type(exc).__name__)


def build_calendar_background_tasks(config):
    if not getattr(config, "calendar_refresh_enabled", False):
        return []

    def refresh():
        try:
            logger.info("行事曆快取更新: %s", CalendarService().refresh())
        except Exception as exc:
            logger.warning("行事曆更新失敗: %s", type(exc).__name__)

    return [{"name": "calendar_refresh", "task": refresh, "interval_seconds": 6 * 60 * 60,
             "run_immediately": True}]


def earnings_evidence(code, now=None):
    """證據上下文單點；快取錯誤不拖垮分析，不呼叫外部資料源。"""
    try:
        row = CalendarService().next_earnings(code, now=now)
        if row:
            return {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in row.items()}
    except Exception as exc:
        logger.warning("下次財報證據讀取失敗 %s: %s", code, type(exc).__name__)
    return {"code": code, "date": None, "detail": "日期未定"}


def earnings_prompt(evidence, report_language="zh-TW"):
    if not evidence:
        return ""
    import json

    label, rule = {
        "zh-TW": ("下次財報日（證據）", "只作日期風險證據，不改評分；未定不可推算，推估不可當確認。日期依來源時區。"),
        "zh": ("下次财报日（证据）", "仅作日期风险证据，不改评分；未定不可推算，推估不可当确认。日期依来源时区。"),
        "en": ("Next earnings (evidence)", "Date risk evidence only; do not change scores. Do not invent unknown dates or treat estimates as confirmed. Use the source timezone."),
        "ko": ("다음 실적 발표일 (근거)", "날짜 위험 근거로만 사용하며 점수를 변경하지 마세요. 미정 날짜를 추정하거나 예상일을 확정일로 취급하지 마세요. 출처 시간대를 사용하세요."),
    }[report_language]
    return f"\n### {label}\n{rule}\n{json.dumps(evidence, ensure_ascii=False, default=str)}\n"
