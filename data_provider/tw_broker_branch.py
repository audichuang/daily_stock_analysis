"""台股券商分點買賣超（前 15 名買超／賣超）——富邦 DJ 個股主力進出頁，按需查詢、不入庫。

來源是券商網站（非交易所官方），只列**前 15 名**買超與賣超分點，所以：

- HHI 只能算「前 15 名買超分點」內部的集中度（``hhi_top15``），**不是**全市場分點的 HHI；
  報告引用時必須標「前 15 名近似」。完整分點要 TWSE／TPEx 買賣日報表（有驗證碼）或付費資料。
- 「平均買超成本」是頁面自帶的「前 15 名買超金額 / 張數」，不是全體大戶成本。

單位：張。頁面自帶查詢區間（``getYMD1``／``getYMD2``），與請求不符就拒收。
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm"
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
_TAG = re.compile(r"<[^>]+>")


def _num(text: str) -> Optional[float]:
    s = _TAG.sub("", text).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _ymd(s: str) -> _dt.date:
    return _dt.datetime.strptime(s, "%Y/%m/%d").date()   # 頁面寫 2026/8/28（月日不補零）


def parse_branch_page(html: str, start: _dt.date, end: _dt.date) -> Optional[dict]:
    """頁面 -> ``{start, end, buy: [...], sell: [...], buy_total, sell_total, avg_buy_cost, avg_sell_cost}``。

    ``buy``／``sell`` 每列 ``{"branch", "buy", "sell", "net", "share_pct"}``，net 一律為正（賣超也是正數）。
    查無資料、區間不符回 None。"""
    # 頁面 JS：getYMD1 是迄日、getYMD2 是起日（單日查詢兩者相同，弄反也看不出來）
    m1 = re.search(r"getYMD1 = '([\d/]+)'", html)
    m2 = re.search(r"getYMD2 = '([\d/]+)'", html)
    if not m1 or not m2 or (_ymd(m2.group(1)), _ymd(m1.group(1))) != (start, end):
        logger.warning("[broker-branch] 頁面區間 %s~%s ≠ 請求 %s~%s，拒收",
                       m1 and m1.group(1), m2 and m2.group(1), start, end)
        return None
    buy, sell = [], []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
        if len(cells) != 10 or "zco0.djhtm" not in row:
            continue
        for side, part in ((buy, cells[:5]), (sell, cells[5:])):
            name = _TAG.sub("", part[0]).strip()
            vals = [_num(c) for c in part[1:]]
            if name and None not in vals[:3]:
                side.append({"branch": name, "buy": vals[0], "sell": vals[1],
                             "net": vals[2], "share_pct": vals[3]})

    def foot(label: str) -> Optional[float]:
        m = re.search(label + r"</td>\s*<td[^>]*>([\d,.]+)</td>", html, re.I)
        return _num(m.group(1)) if m else None

    if not buy and not sell:
        return None
    return {"start": start, "end": end, "buy": buy, "sell": sell,
            "buy_total": foot("合計買超張數"), "sell_total": foot("合計賣超張數"),
            "avg_buy_cost": foot("平均買超成本"), "avg_sell_cost": foot("平均賣超成本")}


def hhi_top15(rows: list) -> Optional[float]:
    """前 N 名買超（或賣超）分點的 HHI（0~10000），只在這 N 家內部算份額。"""
    nets = [r["net"] for r in rows if r.get("net") and r["net"] > 0]
    total = sum(nets)
    if not total:
        return None
    return round(sum((n / total) ** 2 for n in nets) * 10000, 0)


def fetch_branch_flows(stock_id: str, start: _dt.date, end: Optional[_dt.date] = None,
                       timeout: float = 20) -> Optional[dict]:
    """``stock_id`` 不帶後綴（``3324``）。失敗、查無或區間不符回 None（fail-open）。"""
    end = end or start
    params = {"a": stock_id, "e": f"{start.year}-{start.month}-{start.day}",
              "f": f"{end.year}-{end.month}-{end.day}"}
    try:
        r = requests.get(_URL, params=params, headers={"User-Agent": _UA}, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("[broker-branch] %s %s~%s 抓取失敗: %s", stock_id, start, end, exc)
        return None
    out = parse_branch_page(r.content.decode("big5", errors="replace"), start, end)
    if out is not None:
        out["hhi_buy_top15"] = hhi_top15(out["buy"])
    return out
