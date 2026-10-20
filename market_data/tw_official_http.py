"""報告當下即時抓官方端點（TWSE／TPEx／期交所／MOPS）的共用取用層，只抓不入庫。

為什麼不用 `crawler.requests_get`：那條是給入庫爬蟲用的，每次先向 twse.com.tw 暖
cookie（TWSE 封 IP 時 TPEx／MOPS／期交所也跟著失敗），連線失敗再重試 4 次、每次等
60 秒。報告／盤前流程有人在等，所以這裡：
``timeout=TIMEOUT``、**不重試、不暖 cookie、不共用 session**，失敗就回原因字串，
由呼叫端降級。**``TIMEOUT`` 不是整次請求的上限**：requests 的讀取 timeout 量的是兩次收到位元組
之間的間隔，伺服器一點一點吐資料時單一請求可以遠超過 20 秒；正常情況（連不上或不回應）
約 20 秒內放棄。`screen_tw.collect_live` 先依序打名單 4 個請求（上櫃處置要讀上櫃注意的結果），
再並行跑事件 4 個來源（共 4～6 個請求，`run_sources(parallel=True)`）；整輪沒有總時限，最後一道上限是
每日報告每步 90 分鐘的 timeout。前例是 `data_provider/twse_fetcher.py`（短 timeout、不重試、失敗回
None），但 market_data 不能 import data_provider（它的 ``__init__`` 會拖進 akshare
／tushare／yfinance），所以放在這裡。`crawler.py`／`sources.py` 不受影響。

官方端點常見「回 200 但其實是錯誤」，`error_reason` 集中判斷：

- 狀態碼不是 200（TPEx 不存在的路徑會 302 到 ``/errors``，跟隨後是 200 的 HTML）
- 拿到 HTML 錯誤頁：TWSE 參數不合法時的 HiNet「網站維護中」頁、TPEx 的 404 頁、MOPS
  的安全性封鎖頁；預期 JSON／CSV 卻拿到 HTML（期交所 ``alert("查無資料")``／
  ``alert("日期時間錯誤 DateTime error")`` 即此類，訊息會帶進原因）
- 預期 JSON 卻不是 JSON
- 預期 CSV 卻只有表頭一行（期交所 P/C 比查非交易日／未來日的回法）

**它不判斷的事**（屬於各來源自己的新鮮度規則，呼叫端一定要另外比對回應自帶的日期）：

- TPEx bulletin 日期參數不合法時**靜默退回今天**——要比對 ``tables[0].startDate``
- 非交易日回 ``data: []``——空資料無法證明新鮮，不可當成「0 檔」
- TWSE openapi notice 回一筆 ``Code == ""`` 的佔位列
- 端點凍結但照樣回 200（見 repo 根 `AGENTS.md` §10）
"""

import re
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Callable

import requests
from urllib3.exceptions import InsecureRequestWarning

from market_data.crawler import _UA

# (連線, 讀取) 秒數；讀取是「兩次收到位元組的間隔」不是總時長，見模組說明。不重試。
TIMEOUT = (5, 15)

# MOPS 憑證鏈不完整，入庫爬蟲也是 verify=False。只對這個主機靜音，而且在 import 時設一次：
# `warnings.catch_warnings()` 改的是行程全域的過濾器、不是執行緒安全的，並行抓取時會互相蓋掉。
warnings.filterwarnings("ignore", category=InsecureRequestWarning,
                        message=r"Unverified HTTPS request is being made to host 'mopsov\.twse\.com\.tw'")

_ALERT_RE = re.compile(r"alert\(\s*[\"']([^\"']*)[\"']")
# (辨識字串, 原因)：依序比對，先命中者為準。
# 這張表只替錯誤標上可讀的原因；偵測靠 ``expect`` 與各來源的解析器。
_KNOWN_ERROR_PAGES = (
    ("errorpage-twseweb.cdn.hinet.net", "TWSE HiNet 錯誤頁（網站維護中，多半是參數不合法或被擋）"),
    ("網站維護中", "TWSE HiNet 錯誤頁（網站維護中，多半是參數不合法或被擋）"),
    ("<title>404 - 證券櫃檯買賣中心", "TPEx 錯誤頁（404，路徑或參數不對）"),
    ("FOR SECURITY REASONS", "MOPS 安全性封鎖頁"),
)


def md(day):
    """報告與狀態說明裡的日期一律寫成 ``MM/DD``（補零），例如 ``10/08``。"""
    return f"{day:%m/%d}"


@dataclass(frozen=True)
class SourceStatus:
    """單一即時來源這一輪的狀態，給報告的 blind_spots／來源清單用。

    ``ok=False`` 代表「這個來源這一輪不可用」，**不是**「沒有事件／0 檔」；
    ``proven=False`` 代表「可用，但新鮮度無法自證」（例如 MOPS 法說會表上沒有資料日期）：
    它的命中照列，但**不算查過**——`checked_markets` 不收它，沒命中的候選仍是未經檢查。
    ``note`` 寫原因或限制，給人和 agent 看。"""

    name: str
    ok: bool
    note: str = ""
    proven: bool = True

    @property
    def checked(self):
        """可以拿來宣稱「查過、沒有」：可用且新鮮度已證明。"""
        return self.ok and self.proven

    @property
    def label(self):
        if not self.ok:
            return "不可用"
        return "可用" if self.proven else "可用（未證明新鮮）"

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Step:
    """`run_sources` 的一步。``fn(done)`` 回 ``(payload, note)``；``done`` 是到目前為止的狀態
    （並行時永遠是空 tuple）。``proven=False``：這個來源成功時也只記成「未證明新鮮」。"""

    name: str
    fn: Callable
    proven: bool = True


class FormatChanged(ValueError):
    """回應結構與預期不符（端點改版或拿到別的頁面）。"""


def run_sources(steps, *, parallel=False):
    """跑一串 `Step`，回 ``(results, statuses)``；**不往外拋** ``Exception``。

    預設依序跑，``fn(done)`` 收到「到目前為止」的狀態清單（讓後面的來源能以前面的結果當旁證）。
    ``parallel=True`` 時每步各開一條執行緒同時跑，``done`` 一律是空 tuple——只給彼此不依賴的來源用。
    兩種模式的 ``results``（``[(名稱, payload)]``）與 ``statuses`` 都**依 steps 原順序**，與完成先後無關。
    失敗只把該來源記成 ``ok=False``、原因取例外訊息。只接 ``Exception``：測試的連外守門刻意繼承
    ``BaseException``，放寬就會被吞掉（並行時 `Future.result()` 會把它原樣拋回呼叫端）。"""
    statuses, results = [], []

    def record(step, call):
        try:
            payload, note = call()
        except Exception as error:  # 單一來源失敗只降級這一個來源
            statuses.append(SourceStatus(step.name, False, str(error) or type(error).__name__))
            return
        statuses.append(SourceStatus(step.name, True, note, step.proven))
        results.append((step.name, payload))

    if not parallel:
        for step in steps:
            record(step, lambda: step.fn(statuses))
        return results, statuses
    with ThreadPoolExecutor(max_workers=max(len(steps), 1)) as pool:
        futures = [pool.submit(step.fn, ()) for step in steps]
        for step, future in zip(steps, futures):
            record(step, future.result)
    return results, statuses


def checked_markets(statuses, source_market):
    """``source_market``（來源名稱 → 市場）裡，該市場每個來源都「可用且新鮮度已證明」的市場集合。

    ``proven=False`` 的來源（可用但未證明新鮮）不算：它沒列出的東西不能寫成「查過、沒有」。"""
    ok = {s.name for s in statuses if s.checked}
    return {market for market in set(source_market.values())
            if all(name in ok for name, m in source_market.items() if m == market)}


def _send(method, url, **kwargs):
    """唯一真正發出請求的地方（測試的接縫）。"""
    return requests.request(method, url, **kwargs)


def _short(raw, limit=60):
    text = raw.decode("utf-8", errors="replace").strip()
    return " ".join(text.split())[:limit]


def error_reason(resp, expect=None):
    """回應若是「其實是錯誤」回原因字串，看起來可用回 None。

    ``expect``：``"json"``、``"csv"`` 或 None（呼叫端要的就是 HTML；只做狀態碼與
    已知錯誤頁判斷）。預期 JSON／CSV 時任何 HTML 都算錯誤，``alert("…")`` 的訊息
    會帶進原因。
    錯誤頁一律以 UTF-8 解碼原始位元組：期交所正常 CSV 是 MS950，但錯誤頁是 UTF-8
    HTML，用 cp950 或 ``resp.text``（無 charset 時 requests 猜 ISO-8859-1）解會把
    ``alert`` 訊息變亂碼。"""
    if resp.status_code != 200:
        return f"HTTP {resp.status_code}"
    raw = resp.content or b""
    # 以內容判斷是不是 HTML，不看 Content-Type：期交所正常的 CSV 下載也標
    # ``text/html;charset=MS950``（2026-10-20 實測），錯誤頁則是 ``text/html;charset=UTF-8``。
    if raw.lstrip().startswith(b"<"):
        text = raw.decode("utf-8", errors="replace")
        redirected = "（曾被轉址）" if resp.history else ""
        for needle, reason in _KNOWN_ERROR_PAGES:
            if needle in text:
                return reason + redirected
        if expect is None:
            # 呼叫端本來就要 HTML（MOPS 表格頁）：只認上面的已知錯誤頁。不看 alert(——
            # 期交所、法規查詢的正常 HTML 頁裡就有 alert( 呼叫，會誤判。
            return None
        match = _ALERT_RE.search(text)
        if match:
            return f"錯誤頁 alert：{match.group(1)}{redirected}"
        return f"預期 {expect.upper()} 卻拿到 HTML：{_short(raw)}{redirected}"
    if not raw.strip():
        return "空回應"
    if expect == "json":
        try:
            resp.json()
        except ValueError:
            return f"非 JSON：{_short(raw)}"
    elif expect == "csv":
        lines = [line for line in raw.splitlines() if line.strip()]
        if len(lines) <= 1:
            return "只有表頭、沒有資料列（多半是非交易日或未來日）"
    return None


def _fetch(method, url, expect, verify, **kwargs):
    try:
        resp = _send(method, url, headers={"User-Agent": _UA}, timeout=TIMEOUT, verify=verify, **kwargs)
    except requests.RequestException as error:
        return None, f"連線失敗：{type(error).__name__}"
    return resp, error_reason(resp, expect)


def get(url, params=None, *, expect=None, verify=True):
    """GET 一次，回 ``(Response|None, reason)``。

    ``reason is None`` 才代表可用；有回應但判成錯誤時 Response 仍一併回傳（方便看
    標頭／記錄），連線失敗時 Response 為 None。只接 ``requests.RequestException``，
    程式 bug 照常往上拋。"""
    return _fetch("GET", url, expect, verify, params=params)


def post(url, data=None, *, expect=None, verify=True):
    """POST 一次（表單），回傳約定同 `get`。"""
    return _fetch("POST", url, expect, verify, data=data)
