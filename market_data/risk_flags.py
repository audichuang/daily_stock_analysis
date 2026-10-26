"""處置股／注意股旗標：報告當下即時抓四份官方名單（上市處置、上市注意、上櫃處置、上櫃注意），只抓不入庫。

只**標記**、不剔除：上市處置的歷史回測（`docs/research/2026-10-26-exp-disposal-delay.md`）顯示
剔除讓突破池變差、延後進場 inconclusive。旗標回答的問題只有一個——「下一個交易日這檔能不能
正常成交」——所以處置名單以 ``next_session`` 查詢，注意名單以 ``as_of`` 查詢。

每份名單各自判新鮮度，證明不了就整份記成不可用（``SourceStatus.ok=False``），**絕不當成
「0 檔」**：

- 上市處置（TWSE rwd punish）：title 的查詢區間須等於送出的 ``next_session``。title **有時**附
  「資訊更新日期」（2026-10-20 晚上有、10-21 07:30 沒有）：有就須 ≥ ``as_of``，早於基準日一律拒收；
  沒有時改用旁證——有任一列的公布日期等於 ``as_of``，或同一輪的上市注意已判可用（較弱）。
  這欄不隨查詢區間變（查過去的區間也回當天），是最後發布日還是伺服器當日尚未區分。
- 上市注意（TWSE rwd notice）：非交易日與未來日都回 ``stat=OK`` 加空 data，所以 data 必須
  非空、且每一列的「日期」都等於 ``as_of``。
- 上櫃注意（TPEx bulletin attention）：日期參數不合法時**靜默退回今天**，所以回應的
  ``tables[0].startDate／endDate`` 須等於送出的值；其餘規則同上市注意。
- 上櫃處置（TPEx bulletin disposal）：表上沒有更新日期，只能用旁證——有任一列的公布日期等於
  ``as_of``，或同一輪的上櫃注意已判可用。**四份裡新鮮度證據最弱**：注意與處置是兩張表，
  注意表已更新不保證處置表也更新了。

兩份處置名單的判準都沒有在「交易日收盤後、當日公告出齊前」實測過；抓取時點由呼叫端的
`health.expected_session()` 決定（17:00 翻到當天），與公告時間無關。隔天早上跑不受影響。

HTTP 一律走 `market_data.tw_official_http`（短 timeout、不重試）。代號一律以字串精確比對，
權證（6 碼）與可轉債（5 碼）留在名單裡也對不到候選，不另外過濾。
"""

import argparse
import datetime
import re
import sys
from dataclasses import dataclass

from market_data import tw_official_http as http
from market_data.sources import _roc_slash_to_date, _roc_to_date
from market_data.tw_official_http import FormatChanged, Step, md, run_sources

TWSE_PUNISH_URL = "https://www.twse.com.tw/rwd/zh/announcement/punish"
TWSE_NOTICE_URL = "https://www.twse.com.tw/rwd/zh/announcement/notice"
TPEX_DISPOSAL_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal"
TPEX_ATTENTION_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/attention"

# 人工查詢頁（名單取不到時印在報告裡）
MANUAL_LINKS = {
    "twse": "https://www.twse.com.tw/zh/announcement/punish.html",
    "tpex": "https://www.tpex.org.tw/zh-tw/announce/market/disposal.html",
}

# 來源名稱 → 所屬市場。名稱也是報告與 JSON 裡的顯示字串。
SOURCE_MARKET = {
    "上市處置": "twse",
    "上市注意": "twse",
    "上櫃處置": "tpex",
    "上櫃注意": "tpex",
}

DISPOSING = "處置中"
UPCOMING = "即將處置"
ATTENTION = "注意股"
_PRIORITY = {DISPOSING: 0, UPCOMING: 1, ATTENTION: 2}

_UPDATE_RE = re.compile(r"資訊更新日期：\s*(\d+/\d+/\d+)")
_SLASH_RANGE_RE = re.compile(r"\(\s*(\d+/\d+/\d+)\s*至\s*(\d+/\d+/\d+)\s*\)")
_CJK_RANGE_RE = re.compile(r"\(\s*(\d+年\d+月\d+日)\s*至\s*(\d+年\d+月\d+日)")


class Unproven(ValueError):
    """回應可解析，但證明不了是預期那天的名單。"""


@dataclass(frozen=True)
class RiskHit:
    """單檔命中。``flag`` 為處置中／即將處置／注意股；``flag == ""`` 只用在「查過、不在名單」的哨兵值。"""

    flag: str
    name: str
    detail: str


CLEAN = RiskHit("", "", "")


def _roc(day):
    """2026-10-20 -> "115/10/20"（TPEx 回應裡的日期寫法）。"""
    return f"{day.year - 1911}/{day.month:02d}/{day.day:02d}"


def _tpex_name(text):
    """TPEx 名稱欄常帶連結註記（例如「律勝(第一次處置)」），只留括號前的名稱。"""
    return str(text).split("(")[0].strip()


def _columns(fields, wanted):
    """依回應的 ``fields`` 動態定位欄位；缺欄就當改版。"""
    names = [str(f).strip() for f in fields or []]
    missing = [w for w in wanted if w not in names]
    if missing:
        raise FormatChanged(f"缺欄位 {missing}（端點可能改版）")
    return {w: names.index(w) for w in wanted}


def _period(text):
    """"115/10/21～115/10/28" 或 "115/10/21~115/10/28" -> (起, 迄)。"""
    start, end = str(text).replace("～", "~").split("~")
    return _roc_slash_to_date(start), _roc_slash_to_date(end)


def _disposal_hits(rows, cols, as_of, next_session, name_cleaner=str.strip):
    """處置列 → ``{代號: RiskHit}``。只收處置期間涵蓋 ``next_session`` 的列。

    同一代號多列（第一次、第二次處置期間重疊）時：任一列在 ``as_of`` 前已開始就是處置中；
    期間與措施取迄日最晚的那一列。迄日可能順延，所以只信當下抓到的值，不自己推算。"""
    best = {}
    for row in rows:
        code = str(row[cols["證券代號"]]).strip()
        start, end = _period(row[cols["period"]])
        if not (start <= next_session <= end):
            continue
        entry = best.setdefault(code, {"started": False, "row": None, "end": None})
        entry["started"] = entry["started"] or start <= as_of
        if entry["end"] is None or end > entry["end"]:
            entry.update(row=row, end=end, start=start)
    hits = {}
    for code, entry in best.items():
        row = entry["row"]
        name = name_cleaner(str(row[cols["證券名稱"]]))
        measure = str(row[cols["處置措施"]]).strip()
        flag = DISPOSING if entry["started"] else UPCOMING
        hits[code] = RiskHit(flag, name, f"{flag} {md(entry['start'])}～{md(entry['end'])}，{measure}")
    return hits


def parse_twse_punish(payload, as_of, next_session, attention_ok=False):
    """title 有「資訊更新日期」就以它為準（早於基準日一律拒收，不拿旁證救）；沒有時（2026-10-21
    07:30 實測：早上的 title 不附這欄）改用旁證——有基準日公布的列，或同輪上市注意可用。"""
    if payload.get("stat") != "OK":
        raise FormatChanged(f"stat={payload.get('stat')!r}")
    title = str(payload.get("title", ""))
    r = _SLASH_RANGE_RE.search(title)
    if not r or {_roc_slash_to_date(r.group(1)), _roc_slash_to_date(r.group(2))} != {next_session}:
        raise Unproven("回應的查詢區間不是送出的日期")
    cols = _columns(payload.get("fields"), ["公布日期", "證券代號", "證券名稱", "處置起迄時間", "處置措施"])
    cols["period"] = cols["處置起迄時間"]
    data = payload.get("data") or []
    m = _UPDATE_RE.search(title)
    if m:
        updated = _roc_slash_to_date(m.group(1))
        if updated < as_of:
            raise Unproven(f"資訊更新日期 {md(updated)} 早於基準日 {md(as_of)}")
        proof = f"資訊更新 {md(updated)}"
    elif any(_roc_slash_to_date(str(row[cols["公布日期"]]).lstrip("*")) == as_of for row in data):
        proof = "新鮮度旁證：有基準日公布的列"
    elif attention_ok:
        proof = "新鮮度旁證：以同輪上市注意可用為旁證（較弱）"
    else:
        raise Unproven("title 無資訊更新日期，且無基準日公布的列、上市注意也不可用，無法證明新鮮")
    return _disposal_hits(data, cols, as_of, next_session), proof


def parse_twse_notice(payload, as_of):
    if payload.get("stat") != "OK":
        raise FormatChanged(f"stat={payload.get('stat')!r}")
    r = _CJK_RANGE_RE.search(str(payload.get("title", "")))
    if not r or {_roc_to_date(r.group(1)), _roc_to_date(r.group(2))} != {as_of}:
        raise Unproven("回應的查詢區間不是基準日")
    data = payload.get("data") or []
    if not data:
        raise Unproven("空回應無法證明新鮮（非交易日／未發布也回空）")
    cols = _columns(payload.get("fields"), ["證券代號", "證券名稱", "累計次數", "日期"])
    hits = {}
    for row in data:
        day = _roc_slash_to_date(str(row[cols["日期"]]).strip().replace(".", "/"))
        if day != as_of:
            raise Unproven(f"含非基準日的列（{md(day)}）")
        code = str(row[cols["證券代號"]]).strip()
        count = str(row[cols["累計次數"]]).strip()
        hits[code] = RiskHit(ATTENTION, str(row[cols["證券名稱"]]).strip(), f"注意股，累計 {count} 次")
    return hits, f"{len(data)} 列皆為 {md(as_of)}"


def _tpex_table(payload, sent):
    if str(payload.get("stat", "")).lower() != "ok":
        raise FormatChanged(f"stat={payload.get('stat')!r}")
    tables = payload.get("tables") or []
    if not tables:
        raise FormatChanged("沒有 tables")
    table = tables[0]
    want = _roc(sent)
    if table.get("startDate") != want or table.get("endDate") != want:
        # 參數不合法時 TPEx 靜默退回今天，外層 `date` 只是照抄查詢，不能拿來驗
        raise Unproven(f"回應區間 {table.get('startDate')}~{table.get('endDate')} 不是送出的 {want}")
    return table


def parse_tpex_attention(payload, as_of):
    table = _tpex_table(payload, as_of)
    data = table.get("data") or []
    if not data:
        raise Unproven("空回應無法證明新鮮（非交易日／未發布也回空）")
    # 「累計」欄實測是當天名單的總檔數（每列都一樣），不是該檔的累計次數，所以不印
    cols = _columns(table.get("fields"), ["證券代號", "證券名稱", "公告日期"])
    hits = {}
    for row in data:
        day = _roc_slash_to_date(row[cols["公告日期"]])
        if day != as_of:
            raise Unproven(f"含非基準日的列（{md(day)}）")
        code = str(row[cols["證券代號"]]).strip()
        hits[code] = RiskHit(ATTENTION, _tpex_name(row[cols["證券名稱"]]), "注意股")
    return hits, f"{len(data)} 列皆為 {md(as_of)}"


def parse_tpex_disposal(payload, as_of, next_session, attention_ok):
    table = _tpex_table(payload, next_session)
    cols = _columns(table.get("fields"), ["公布日期", "證券代號", "證券名稱", "處置起訖時間", "處置措施"])
    cols["period"] = cols["處置起訖時間"]
    data = table.get("data") or []
    announced_today = any(
        _roc_slash_to_date(str(row[cols["公布日期"]]).lstrip("*")) == as_of for row in data)
    if not (announced_today or attention_ok):
        raise Unproven("表上無更新日期，且無基準日公布的列、上櫃注意也不可用，無法證明新鮮")
    proof = "有基準日公布的列" if announced_today else "以同輪上櫃注意可用為旁證"
    hits = _disposal_hits(data, cols, as_of, next_session, name_cleaner=_tpex_name)
    return hits, f"新鮮度旁證：{proof}（四份裡最弱）"


def _get_json(url, params):
    resp, reason = http.get(url, params=params, expect="json")
    if reason:
        raise FormatChanged(reason)
    return resp.json()


def fetch_risk_flags(as_of, next_session):
    """抓四份名單，回 ``(flags, statuses)``；**不往外拋** ``Exception``。``as_of``／``next_session`` 為 date。

    ``flags``：``{代號: RiskHit}``，同一檔同時是處置與注意時 flag 取處置、detail 兩者都寫。
    市場別不放在命中裡：逐檔該信哪個市場由呼叫端的市場對照（種子檔）決定。
    ``statuses``：四個 `SourceStatus`，名稱見 ``SOURCE_MARKET``。
    必須**依序**跑（不能 ``parallel=True``）：上櫃處置的新鮮度旁證要讀同輪上櫃注意的結果。"""
    ymd = lambda d: f"{d:%Y%m%d}"  # noqa: E731
    slash = lambda d: f"{d:%Y/%m/%d}"  # noqa: E731
    steps = [
        Step("上市注意", lambda done: parse_twse_notice(_get_json(
            TWSE_NOTICE_URL, {"response": "json", "startDate": ymd(as_of),
                              "endDate": ymd(as_of)}), as_of)),
        # 上市處置 title 不附更新日期時要讀同輪「上市注意」當旁證，所以排在它之後
        Step("上市處置", lambda done: parse_twse_punish(_get_json(
            TWSE_PUNISH_URL, {"response": "json", "startDate": ymd(next_session),
                              "endDate": ymd(next_session)}),
            as_of, next_session, attention_ok=any(s.ok for s in done if s.name == "上市注意"))),
        Step("上櫃注意", lambda done: parse_tpex_attention(_get_json(
            TPEX_ATTENTION_URL, {"startDate": slash(as_of), "endDate": slash(as_of),
                                 "response": "json"}), as_of)),
        # 上櫃處置的新鮮度旁證要讀同一輪「上櫃注意」的結果，所以必須排在它之後
        Step("上櫃處置", lambda done: parse_tpex_disposal(_get_json(
            TPEX_DISPOSAL_URL, {"startDate": slash(next_session), "endDate": slash(next_session),
                                "response": "json"}),
            as_of, next_session, attention_ok=any(s.ok for s in done if s.name == "上櫃注意"))),
    ]
    results, statuses = run_sources(steps)
    flags = {}
    for _, hits in results:
        for code, hit in hits.items():
            cur = flags.get(code)
            if cur is None:
                flags[code] = hit
                continue
            first, second = sorted([cur, hit], key=lambda h: _PRIORITY[h.flag])
            flags[code] = RiskHit(first.flag, first.name, f"{first.detail}；{second.detail}")
    return flags, statuses


def checked_markets(statuses):
    """兩份名單（處置＋注意）都可用的市場；只有這些市場的「不在名單」才算查過。"""
    return http.checked_markets(statuses, SOURCE_MARKET)


def main(argv=None):
    """查單檔：``uv run python -m market_data.risk_flags 2424 3354 --as-of 2026-10-20``。"""
    from market_data.health import expected_session, sessions_after

    p = argparse.ArgumentParser(description="即時查處置股／注意股旗標（上市＋上櫃，只讀官方名單、不入庫）")
    p.add_argument("codes", nargs="+", help="股票代號（2424 或 2424.TW／3354.TWO 皆可）")
    p.add_argument("--as-of", default=None, help="基準日 YYYY-MM-DD（預設：預期場次）")
    a = p.parse_args(argv)
    as_of = datetime.date.fromisoformat(a.as_of) if a.as_of else expected_session()
    nxt = sessions_after(as_of, 1) if as_of else None
    if as_of is None or nxt is None:
        print("交易日曆（XTAI）不可用，無法決定基準日與下一個交易日", file=sys.stderr)
        return 1
    flags, statuses = fetch_risk_flags(as_of, nxt)
    print(f"基準日 {as_of}，下一個交易日 {nxt}")
    for s in statuses:
        print(f"- {s.name}：{'✓' if s.ok else '✗'} {s.note}")
    checked = checked_markets(statuses)
    for code in a.codes:
        # 名單裡的鍵是裸證券代號；repo 慣例的 .TW／.TWO 後綴要先去掉，否則永遠對不到、
        # 而且在四份名單都可用時會被印成看似查過的「不在名單」
        hit = flags.get(code.strip().split(".")[0].upper())
        if hit:
            print(f"{code}：{hit.detail}")
        else:
            print(f"{code}：不在可用名單中" + ("" if len(checked) == 2 else "（有名單不可用，不代表沒有）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
