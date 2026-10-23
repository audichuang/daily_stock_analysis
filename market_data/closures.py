"""台股臨時休市日（颱風假等）：交易日曆（exchange_calendars XTAI）不知道的休市。

證交所休市原則：臺北市全體公教機關全日或上午停止上班 → 集中與櫃買市場全日休市（下午停班照常交易）。官方休市 API
（holidaySchedule）只列國定假日、不會補颱風假，所以這裡讀人事行政總處的停班停課頁，
偵測到就記進休市清單檔；`trading_calendar.is_market_open("tw", …)` 與
`health.expected_session` 都會讀這份檔，之後幾天（例如連假後第一個交易日）仍然知道
那天沒開盤。

    python -m market_data.closures            # 今天台股開市回 0、休市回 1（排程 precheck 用）
    python -m market_data.closures --date 2026-10-23

清單檔：``TW_ADHOC_CLOSED_FILE``，預設 ``<repo>/data/tw_adhoc_closed_dates.txt``；
一行一個 ``YYYY-MM-DD``，``#`` 之後是註解，可手動加（其他原因的臨時休市）。
"""

import argparse
import datetime
import os
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

_TAIPEI = ZoneInfo("Asia/Taipei")
DGPA_URL = "https://www.dgpa.gov.tw/typh/daily/nds.html"
_DEFAULT_FILE = Path(__file__).resolve().parents[1] / "data" / "tw_adhoc_closed_dates.txt"
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 臺北市那一列的公告文字（市名儲存格的下一個 <TD>）。用中文市名當錨點、不用 headers
# 屬性：2025-11 前的版面是 `headers='city_Name'`（單引號、沒有英文市名）。
_TAIPEI_ROW_RE = re.compile(r">\s*[臺台]北市\s*</FONT>\s*</TD>\s*<TD[^>]*>(.*?)</TD>", re.S)
_UPDATED_RE = re.compile(r"更新時間：\s*(\d{4})/(\d{1,2})/(\d{1,2})")
# 證交所休市原則：臺北市全體公教機關「全日」或「上午」停止上班 → 全日休市；只有下午停班照常交易。
# 每一句（以「。」切）都要以這段開頭：「臺北市士林區某國小:今天停止上班」這種校級／區域停班
# 也寫在臺北市欄裡，不能算全市。
_CLOSED_SENTENCE_RE = re.compile(r"^(今天|明天)(上午)?停止上班")


def closed_file():
    return Path(os.environ.get("TW_ADHOC_CLOSED_FILE") or _DEFAULT_FILE)


def adhoc_closed_dates(path=None):
    """清單檔裡的臨時休市日；檔案不存在或讀不到回空集合。"""
    try:
        text = Path(path or closed_file()).read_text(encoding="utf-8")
    except OSError:
        return set()
    dates = set()
    for line in text.splitlines():
        m = _DATE_RE.match(line.split("#", 1)[0].strip())
        if m:
            try:
                dates.add(datetime.date.fromisoformat(m.group(0)))
            except ValueError:
                continue
    return dates


def parse_dgpa(html):
    """停班停課頁 → 臺北市全日或上午停班（＝台股休市）的日期集合；版面認不出來回 None（不當成「沒停班」）。

    頁面的「今天／明天」是相對它自己的「更新時間」，不是相對抓取當下：
    前一晚公告的「明天停止上班」到了隔天早上若還沒更新，指的仍是今天。"""
    updated = _UPDATED_RE.search(html)
    row = _TAIPEI_ROW_RE.search(html)
    if not updated or not row:
        return None
    base = datetime.date(*map(int, updated.groups()))
    text = re.sub(r"<[^>]+>|\s+", "", row.group(1))
    offset = {"今天": 0, "明天": 1}
    return {base + datetime.timedelta(days=offset[m.group(1)])
            for m in map(_CLOSED_SENTENCE_RE.match, text.split("。")) if m}


def fetch_dgpa_closures(timeout=10):
    """抓停班停課頁；連不上或版面變了回 None。"""
    import requests

    try:
        r = requests.get(DGPA_URL, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        r.encoding = "utf-8"
        closures = parse_dgpa(r.text)
    except Exception as exc:  # noqa: BLE001 - fail-open: a broken page must not stop schedules
        print(f"WARN: 讀不到停班停課頁（{exc}），只依交易日曆判斷", file=sys.stderr)
        return None
    if closures is None:
        print("WARN: 停班停課頁版面認不出來（找不到更新時間或臺北市那一列），只依交易日曆判斷；"
              "請更新 market_data.closures 的解析", file=sys.stderr)
    return closures


def record_closure(day, reason, path=None):
    """把 ``day`` 加進清單檔（已在就不重寫）。"""
    path = Path(path or closed_file())
    if day in adhoc_closed_dates(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{day.isoformat()}  # {reason}\n")


def _calendar_says_open(day):
    """XTAI 交易日曆（不含臨時休市清單）；日曆取不到時 fail-open。"""
    try:
        import exchange_calendars as xcals

        return bool(xcals.get_calendar("XTAI").is_session(day))
    except Exception:  # noqa: BLE001 - calendar unavailable: fail-open like trading_calendar
        return True


def tw_closed_reason(day, fetch=fetch_dgpa_closures, path=None, today=None):
    """``day`` 台股休市的原因；開市回 None。停班停課頁只在 ``day`` 是今天時才查。"""
    if day in adhoc_closed_dates(path):
        return f"臨時休市清單（{path or closed_file()}）"
    if not _calendar_says_open(day):
        return "交易日曆：非交易日"
    if day == (today or datetime.datetime.now(_TAIPEI).date()):
        closures = fetch()
        if closures and day in closures:
            record_closure(day, "人事行政總處：臺北市停止上班", path)
            return "人事行政總處：臺北市停止上班（已記入臨時休市清單）"
    return None


def main(argv=None):
    p = argparse.ArgumentParser(prog="market_data.closures",
                                description="台股今天開市回 0、休市回 1")
    p.add_argument("--date", type=datetime.date.fromisoformat, default=None)
    args = p.parse_args(argv)
    day = args.date or datetime.datetime.now(_TAIPEI).date()
    reason = tw_closed_reason(day)
    print(f"{day} 台股{'休市：' + reason if reason else '開市'}")
    return 1 if reason else 0


if __name__ == "__main__":
    sys.exit(main())
