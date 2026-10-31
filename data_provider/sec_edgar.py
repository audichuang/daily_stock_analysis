"""SEC／FINRA 一手證據；只讀、按需、共享基本面期限，不影響評分。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging
import re
import threading
import time
from urllib.parse import quote
from xml.etree import ElementTree

from bs4 import BeautifulSoup
import requests

from .us_index_mapping import is_us_stock_code

logger = logging.getLogger(__name__)
_SEC_LOCK = threading.Lock()
_SEC_LAST_REQUEST = 0.0
_TICKERS_LOCK = threading.Lock()
_TICKERS: dict = {}
_TICKERS_AT = 0.0
FINRA_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _number(value):
    import math
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def filing_rows(columns: dict) -> list[dict]:
    return [{key: values[i] for key, values in columns.items() if isinstance(values, list) and i < len(values)}
            for i in range(len(columns.get("form", [])))]


def earnings_excerpt(html: str, limit: int = 6000) -> str:
    """保留原文；財測／重點段落優先，不能用封面或附件檔名代替內容。"""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "ix:header"]):
        node.decompose()
    lines = [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n").splitlines()]
    lines = list(dict.fromkeys(line for line in lines if line))
    text = " ".join(lines)
    if not re.search(r"earnings|financial results|quarter.{0,20}results", text, re.I):
        return ""
    if not re.search(r"revenue|net income|earnings per share|\bEPS\b", text, re.I):
        return ""
    priority = set()
    for i, line in enumerate(lines):
        if re.search(r"outlook|guidance|forecast|highlights|expects?\b", line, re.I):
            priority.update(range(max(0, i - 1), min(len(lines), i + 10)))
    ordered = [lines[i] for i in sorted(priority)] + [line for i, line in enumerate(lines) if i not in priority]
    return "\n".join(ordered)[:limit]


def parse_form4(xml: str, *, now: date) -> dict:
    """同一 CIK 各股別的普通股合計；衍生證券單位另排除，不混成股數。"""
    # 外部 XML 不允許 DTD／實體宣告。
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("Form 4 DTD is not allowed")
    root = ElementTree.fromstring(xml)
    for node in root.iter():
        node.tag = node.tag.split("}")[-1]
    result = {"buy_shares": 0, "sell_shares": 0, "classified_count": 0, "excluded_count": 0}
    for tag in ("nonDerivativeTransaction", "derivativeTransaction"):
        for transaction in root.iter(tag):
            day = _date(transaction.findtext("transactionDate/value"))
            if day is None or not now - timedelta(days=90) <= day <= now:
                continue
            code = transaction.findtext("transactionCoding/transactionCode")
            shares = _number(transaction.findtext("transactionAmounts/transactionShares/value"))
            if tag != "nonDerivativeTransaction" or code not in {"P", "S"} or shares is None:
                result["excluded_count"] += 1
                continue
            result["buy_shares" if code == "P" else "sell_shares"] += shares
            result["classified_count"] += 1
    return result


class SecEdgarClient:
    def __init__(self, user_agent: str, *, request_timeout: float = 3.0):
        self.user_agent = user_agent.strip()
        self.request_timeout = request_timeout

    def _request(self, url: str, *, deadline: float, payload=None):
        global _SEC_LAST_REQUEST
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("official evidence budget exhausted")
        if payload is None:
            if not _SEC_LOCK.acquire(timeout=remaining):
                raise TimeoutError("SEC rate limit budget exhausted")
            try:
                delay = max(0.0, .11 - (time.monotonic() - _SEC_LAST_REQUEST))
                if delay >= deadline - time.monotonic():
                    raise TimeoutError("SEC rate limit budget exhausted")
                time.sleep(delay)
                _SEC_LAST_REQUEST = time.monotonic()
            finally:
                _SEC_LOCK.release()
        # requests 的 connect/read 各用此值，合計仍受剩餘期限約束。
        timeout = min(self.request_timeout, (deadline - time.monotonic()) / 2)
        if timeout <= 0:
            raise TimeoutError("official evidence budget exhausted")
        headers = {"User-Agent": self.user_agent, "Accept": "application/json" if payload is not None else "*/*"}
        if payload is None:
            response = requests.get(url, headers=headers, timeout=timeout)
        else:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        return response

    def _json(self, url, *, deadline, payload=None):
        return self._request(url, deadline=deadline, payload=payload).json()

    def _text(self, url, *, deadline):
        return self._request(url, deadline=deadline).text

    def _cik(self, ticker: str, *, deadline: float):
        global _TICKERS, _TICKERS_AT
        if not _TICKERS_LOCK.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise TimeoutError("SEC ticker cache budget exhausted")
        try:
            if not _TICKERS or time.monotonic() - _TICKERS_AT >= 86400:
                data = self._json("https://www.sec.gov/files/company_tickers.json", deadline=deadline)
                tickers = {row["ticker"].upper(): str(int(row["cik_str"])) for row in data.values()}
                _TICKERS = tickers
                _TICKERS_AT = time.monotonic()
            return _TICKERS.get(ticker.upper().replace(".", "-"))
        finally:
            _TICKERS_LOCK.release()

    @staticmethod
    def _base(cik, row):
        accession = row.get("accessionNumber", "")
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            raise ValueError("invalid SEC accession")
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"

    def _earnings(self, base, primary, *, deadline):
        index = self._json(base + "index.json", deadline=deadline)
        for item in index.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if not name.lower().endswith((".htm", ".html")) or name == primary or "-index" in name or re.fullmatch(r"R\d+\.htm", name):
                continue
            text = earnings_excerpt(self._text(base + quote(name, safe=""), deadline=deadline))
            if text:
                return {"excerpt": text, "excerpt_url": base + quote(name, safe="")}
        return {}

    def sec_evidence(self, ticker: str, *, deadline: float, now: date) -> dict:
        cik = self._cik(ticker, deadline=deadline)
        if cik is None:
            return {}
        data = self._json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", deadline=deadline)
        filings = data.get("filings", {})
        rows = filing_rows(filings.get("recent", {}))
        history_complete = True
        # 高申報量公司 recent 可能不足 90 天，依官方分頁日期繼續讀。
        for page in filings.get("files", []):
            if _date(page.get("filingTo")) and _date(page["filingTo"]) < now - timedelta(days=90) and any(r.get("form") == "10-Q" for r in rows):
                continue
            try:
                name = quote(page["name"], safe="")
                rows.extend(filing_rows(self._json("https://data.sec.gov/submissions/" + name, deadline=deadline)))
            except Exception:
                history_complete = False
                break
        rows.sort(key=lambda r: r.get("filingDate", ""), reverse=True)
        output = {}
        sec = {"cik": cik, "recent_8k": []}
        quarter = next((r for r in rows if r.get("form") == "10-Q" and _date(r.get("filingDate")) and _date(r["filingDate"]) <= now), None)
        if quarter:
            sec["latest_10q_date"] = quarter["filingDate"]
        for row in rows:
            day = _date(row.get("filingDate"))
            if row.get("form") != "8-K" or day is None or not now - timedelta(days=14) <= day <= now:
                continue
            base = self._base(cik, row)
            entry = {"date": row["filingDate"], "accepted_at": row.get("acceptanceDateTime", ""),
                     "items": row.get("items", ""), "url": base + quote(row.get("primaryDocument", ""), safe="")}
            sec["recent_8k"].append(entry)
        if sec["recent_8k"] or quarter:
            output["sec_filings"] = sec
        # 先保留所有申報索引，再取附件；附件失敗仍保留 Item 2.02 一手事實。
        for entry in sec["recent_8k"]:
            if "2.02" not in {item.strip() for item in entry["items"].split(",")}:
                continue
            try:
                base, primary = entry["url"].rsplit("/", 1)
                entry.update(self._earnings(base + "/", primary, deadline=deadline))
            except Exception:
                logger.debug("SEC earnings attachment unavailable", exc_info=True)
        forms = {r["accessionNumber"]: r for r in rows if r.get("form") == "4" and
                 _date(r.get("filingDate")) and now - timedelta(days=90) <= _date(r["filingDate"]) <= now}
        insider = {"window_days": 90, "as_of": now.isoformat(), "buy_shares": 0, "sell_shares": 0,
                   "classified_count": 0, "excluded_count": 0, "filings_read": 0, "filings_available": len(forms),
                   "complete": history_complete}
        for row in forms.values():
            try:
                # xslF345X06/ 是瀏覽器轉換頁；原始 XML 位於 accession 根目錄。
                url = self._base(cik, row) + quote(row["primaryDocument"].split("/")[-1], safe="")
                summary = parse_form4(self._text(url, deadline=deadline), now=now)
                for key, value in summary.items():
                    insider[key] += value
                insider["filings_read"] += 1
            except Exception:
                insider["complete"] = False
                if time.monotonic() >= deadline:
                    break
        insider["complete"] = insider["complete"] and insider["filings_read"] == len(forms)
        if insider["filings_read"] or (not forms and history_complete):
            insider["net_shares"] = insider["buy_shares"] - insider["sell_shares"]
            output["insider_form4"] = insider
        return output

    def finra_short(self, ticker: str, *, deadline: float, now: date) -> dict:
        # 不帶 sortFields；跨 settlementDate 分區排序會回 400。
        rows = self._json(FINRA_URL, deadline=deadline, payload={"limit": 10000, "compareFilters": [
            {"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": ticker.upper()}]})
        # 上限截斷時不能聲稱選到最新；單一代碼實測僅數百筆。
        if len(rows) >= 10000:
            return {}
        valid = [row for row in rows if row.get("symbolCode") == ticker.upper() and
                 _date(row.get("settlementDate")) and _date(row["settlementDate"]) <= now]
        if not valid:
            return {}
        latest = max(valid, key=lambda row: row["settlementDate"])
        result = {"as_of": latest["settlementDate"]}
        for source, key in (("currentShortPositionQuantity", "shares_short"), ("daysToCoverQuantity", "days_to_cover")):
            value = _number(latest.get(source))
            if value is not None:
                result[key] = value
        return result if len(result) > 1 else {}

    def get_evidence(self, ticker: str, *, deadline: float, now: date | None = None) -> dict:
        if not self.user_agent or not is_us_stock_code(ticker):
            return {}
        now = now or datetime.now(timezone.utc).date()
        output = {}
        # FINRA 只需一次；先取避免大量 Form 4 用完預算。兩個來源獨立失敗。
        try:
            short = self.finra_short(ticker, deadline=deadline, now=now)
            if short:
                output["finra_short"] = short
        except Exception:
            logger.debug("FINRA short interest unavailable", exc_info=True)
        try:
            output.update(self.sec_evidence(ticker, deadline=deadline, now=now))
        except Exception:
            logger.debug("SEC filings unavailable", exc_info=True)
        return output
