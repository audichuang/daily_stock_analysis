# -*- coding: utf-8 -*-
"""
===================================
TwseFetcher - 台股大盘统计数据源（仅市场统计，无日线）
===================================

数据来源：台湾证券交易所（TWSE）与柜买中心（TPEx）公开 OpenAPI / RWD 端点，全部免金钥。
覆盖范围：涨跌家数为上市（TWSE）口径（上柜无公开涨跌家数端点）；成交金额与三大法人
为上市+上柜合计。

提供能力：
- get_market_stats(): 涨跌家数、涨停跌停、成交金额，外加三大法人买卖超。

设计说明：
1. 本数据源只服务大盘统计，不参与日线（K线）路由：
   - 不实现真实的 _fetch_raw_data / _normalize_data 取数逻辑
   - is_available_for_request("daily_data") 返回 False
   - 在 DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT 中映射为空集合
2. 加权指数（^TWII）由 YfinanceFetcher 提供；柜买指数 ``^TWOII`` 自 2026-07 起 yfinance 回
   No data，改由本数据源从 TPEx ``tpex_daily_trading_index`` 取官方收盘，放在
   ``get_market_stats()['tpex_index']``（与上柜成交金额同一次 GET、同一道日期比对）。
3. 每个端点独立 try/except，部分降级：若三大法人失败但涨跌家数成功，
   仍返回涨跌家数并省略法人字段；全部失败才返回 {}，绝不向上抛出异常。
"""

import datetime
import logging
import math
import re
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import requests

from .base import BaseFetcher

logger = logging.getLogger(__name__)

# TWSE 上市 免金钥端点
_BREADTH_URL = "https://openapi.twse.com.tw/v1/opendata/twtazu_od"          # 涨跌家数
_INSTITUTIONAL_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"  # 三大法人买卖超
_TRADE_VALUE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"   # 成交金额 + 加权指数
_TRADE_VALUE_RWD_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"  # 同上，按月查询；当日盘后比 OpenAPI 早更新

# 大盤統計（type=MS）：「漲跌證券數合計」表帶漲跌停家數，回應自帶 `date`，是 twtazu_od 凍結後的第二來源
_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
# 「200(4)」＝ 200 家（其中 4 家漲／跌停）
_COUNT_WITH_LIMIT_RE = re.compile(r"^\s*([\d,]+)\s*\(\s*([\d,]+)\s*\)\s*$")

# TPEx 上柜 免金钥 OpenAPI 端点（上柜无公开「涨跌家数」端点，故仅补成交金额与三大法人）
_TPEX_TRADE_VALUE_URL = "https://www.tpex.org.tw/openapi/v1/tpex_daily_trading_index"  # 上柜成交金额 + 柜买指数
_TPEX_INSTITUTIONAL_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_summary"     # 上柜三大法人买卖超彙总

# (connect timeout, read timeout)
_TIMEOUT = (5, 10)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


def _roc_date(value: Any) -> Optional[datetime.date]:
    """民国 ``yyyymmdd``（如 ``1150605``）转 ``date``；无法解析返回 None。"""
    text = str(value or "").strip()
    if len(text) < 7 or not text.isdigit():
        return None
    try:
        return datetime.date(int(text[:-4]) + 1911, int(text[-4:-2]), int(text[-2:]))
    except ValueError:
        return None


def _west_date(value: Any) -> Optional[datetime.date]:
    """西元 ``yyyymmdd``（如 BFI82U 回應的 ``date`` 欄 ``20260821``）转 ``date``。"""
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def _parse_float(value: Any) -> float:
    """将可能含千分位逗号的字符串解析为 float；失败返回 0.0。"""
    if value is None:
        return 0.0
    text = str(value).replace(",", "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except (ValueError, TypeError):
        return 0.0


class TwseFetcher(BaseFetcher):
    """台湾证券交易所大盘统计数据源（仅市场统计）。"""

    name = "TwseFetcher"
    # 数字越小越优先；本数据源不参与日线路由，给一个不影响排序的低优先级即可。
    priority = 95

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    # --- 显式退出日线路由（本数据源仅服务市场统计） ------------------------
    def is_available_for_request(self, capability: str = "") -> bool:
        if capability == "daily_data":
            return False
        return True

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """本数据源不提供日线数据。"""
        raise NotImplementedError("TwseFetcher 仅提供大盘统计，不支持日线数据")

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """本数据源不提供日线数据。"""
        raise NotImplementedError("TwseFetcher 仅提供大盘统计，不支持日线数据")

    # --- 各端点解析 -------------------------------------------------------
    def _fetch_breadth(self, expected_date: Optional[datetime.date]) -> Optional[Dict[str, int]]:
        """涨跌家数（整体市场）。返回 5 个家数键，失败或数据过期返回 None。

        ``expected_date`` 是同一次调用里由 FMTQIK 解析出的最新交易日。**必须逐次比对**：
        这个 openapi 端点会停止更新却照样回 HTTP 200 与结构正确的 JSON——2026-08-23 实测
        ``出表日期`` 仍是 ``1150605``（2026-06-05，冻结 79 天），而当时同一支 fetcher 的
        另外四个端点都是最新交易日。不比对日期的后果不是报错，是 20 份台股大盘复盘印着
        同一组家数、LLM 在上面叠出「跌停 355 家恐触发融资断头」这种完全虚构的叙事
        （见 .claude/reviews/data-fetch-findings.md）。

        拿不到参照日期时**一律拒收**（fail closed）：无法证明新鲜的家数不如没有家数——
        ``_build_stats_block`` 的 ``has_advance_decline`` 用 truthiness 判定，家数保持 0
        会被正确渲染成「没有资料」，而不是「资料是零」。
        """
        try:
            resp = self._session.get(_BREADTH_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            rows = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("[TwseFetcher] 涨跌家数端点失败: %s", e)
            return None

        if not isinstance(rows, list):
            logger.warning("[TwseFetcher] 涨跌家数返回结构异常: 非列表")
            return None

        # 用「股票」列而不是「整體市場」：後者含權證／ETN，分母約 13,181，
        # 而權證帶槓桿又無漲跌幅限制，會主導寬度判讀——實測 2026-06-05 那份
        # 「整體市場」是 3144 漲 / 9578 跌 / 355 跌停，「股票」是 342 / 671 / 10。
        # 報告寫的是「市場寬度」，那指的是股票，不是股票的衍生品。
        target = None
        for row in rows:
            if isinstance(row, dict) and str(row.get("類型", "")).strip() == "股票":
                target = row
                break
        if target is None:
            logger.warning("[TwseFetcher] 涨跌家数未找到「股票」行")
            return None

        snapshot_date = _roc_date(target.get("出表日期"))
        if snapshot_date is None:
            logger.warning(
                "[TwseFetcher] 涨跌家数缺少可解析的「出表日期」(%r)，拒收",
                target.get("出表日期"),
            )
            return None
        if expected_date is None:
            logger.warning(
                "[TwseFetcher] 无最新交易日参照（成交金额端点失败），无法验证涨跌家数 "
                "出表日期=%s 是否新鲜，拒收",
                snapshot_date,
            )
            return None
        if snapshot_date != expected_date:
            logger.warning(
                "[TwseFetcher] 涨跌家数已过期，拒收：出表日期=%s，最新交易日=%s（相差 %d 天）。"
                "端点 %s 停止更新时会照样回 200，故一律以日期为准",
                snapshot_date, expected_date, (expected_date - snapshot_date).days,
                _BREADTH_URL,
            )
            return None

        return {
            "up_count": int(_parse_float(target.get("上漲"))),
            "down_count": int(_parse_float(target.get("下跌"))),
            "flat_count": int(_parse_float(target.get("持平"))),
            "limit_up_count": int(_parse_float(target.get("漲停"))),
            "limit_down_count": int(_parse_float(target.get("跌停"))),
        }

    def _fetch_breadth_mi_index(self, expected_date: Optional[datetime.date]) -> Optional[Dict[str, int]]:
        """涨跌家数（含涨跌停），取自 MI_INDEX ``type=MS`` 的「漲跌證券數合計」表。

        ``twtazu_od`` 凍結（2026-06-05 起）後，家數只剩本地 ``tw_breadth``，**沒有漲跌停**，
        複盤的漲跌停維度永久不可用。這支 rwd 端點回應自帶西元 ``date``，且依請求日期查詢，
        所以可以**逐次比對**：``date`` 不等於 ``expected_date`` 就拒收（盤後尚未發布時
        ``stat`` 不是 ``OK``，同樣回 None）。

        取「股票」欄（與 ``_fetch_breadth`` 同口徑，不含權證／ETN 的「整體市場」欄）；
        上漲／下跌格式為 ``200(4)``＝家數(漲跌停數)，持平為純整數。任何不符一律回 None，
        絕不拋出、絕不猜測。
        """
        if expected_date is None:
            return None
        try:
            resp = self._session.get(
                _MI_INDEX_URL,
                params={"date": expected_date.strftime("%Y%m%d"), "type": "MS", "response": "json"},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("[TwseFetcher] MI_INDEX 涨跌家数端点失败: %s", e)
            return None

        if not isinstance(payload, dict) or payload.get("stat") != "OK":
            return None  # 盤後尚未發布／非交易日：「很抱歉，沒有符合條件的資料!」
        response_date = _west_date(payload.get("date"))
        if response_date != expected_date:
            logger.warning(
                "[TwseFetcher] MI_INDEX 涨跌家数日期不符，拒收：回应 date=%r，最新交易日=%s",
                payload.get("date"), expected_date,
            )
            return None

        try:
            table = next(
                t for t in payload.get("tables") or []
                if isinstance(t, dict) and "漲跌證券數合計" in str(t.get("title") or "")
            )
            col = [str(f).strip() for f in table["fields"]].index("股票")
            cells = {str(row[0]).strip(): str(row[col]).strip() for row in table["data"]}
            up, limit_up = self._parse_count_with_limit(cells["上漲(漲停)"])
            down, limit_down = self._parse_count_with_limit(cells["下跌(跌停)"])
            flat_text = cells["持平"].replace(",", "")
            if not flat_text.isdigit():
                raise ValueError(f"持平欄非整數: {flat_text!r}")
            flat = int(flat_text)
        except (StopIteration, KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
            logger.warning("[TwseFetcher] MI_INDEX 涨跌家数结构不符预期，拒收: %r", e)
            return None

        if up + down + flat <= 0:
            return None
        return {
            "up_count": up,
            "down_count": down,
            "flat_count": flat,
            "limit_up_count": limit_up,
            "limit_down_count": limit_down,
        }

    @staticmethod
    def _parse_count_with_limit(text: str) -> Tuple[int, int]:
        """``"200(4)"`` -> ``(200, 4)``；格式不符拋 ValueError（呼叫端轉成 None）。"""
        m = _COUNT_WITH_LIMIT_RE.match(text)
        if m is None:
            raise ValueError(f"家數格式不符: {text!r}")
        return int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))

    def _fetch_total_amount(self) -> Optional[Tuple[Optional[datetime.date], float]]:
        """最新交易日的 ``(交易日, 成交金额[亿新台币])``。失败返回 None。

        交易日同时充当 ``_fetch_breadth`` 等端点的新鲜度参照——FMTQIK 的最后一列就是 TWSE
        自己认定的最新交易日，比自己算交易日历可靠（台股有连假，weekday 挡不掉）。

        **两个版本取日期较新的一份**：OpenAPI 版盘后常落后一整天以上（2026-09-29 17:05 实测
        仍停在 09-24，rwd 版已有 09-29）。拿落后的当参照，当日新鲜的法人／上柜／本地宽度会全被
        当成过期拒收，成交金额还会印成上一个交易日的。rwd 版按月查询，月初第一个交易日收盘前
        当月没有资料，所以 OpenAPI 仍保留作为另一份候选。
        """
        candidates = [
            latest
            for latest in (
                self._latest_trade_value(self._fetch_fmtqik_rwd_rows(), "rwd"),
                self._latest_trade_value(self._fetch_fmtqik_openapi_rows(), "openapi"),
            )
            if latest is not None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0] or datetime.date.min)

    def _fetch_fmtqik_openapi_rows(self) -> Optional[list]:
        try:
            resp = self._session.get(_TRADE_VALUE_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("[TwseFetcher] 成交金额端点失败（openapi）: %s", e)
            return None

    def _fetch_fmtqik_rwd_rows(self) -> Optional[list]:
        """rwd 版 FMTQIK 当月资料，转成与 OpenAPI 相同的栏位；当月尚无资料或失败返回 None。"""
        from market_data.sources import parse_index_report

        try:
            resp = self._session.get(
                _TRADE_VALUE_RWD_URL,
                params={"date": datetime.date.today().strftime("%Y%m%d"), "response": "json"},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("[TwseFetcher] 成交金额端点失败（rwd）: %s", e)
            return None
        if not isinstance(payload, dict) or payload.get("stat") != "OK":
            return None  # 月初收盘前回「很抱歉，沒有符合條件的資料!」
        try:
            return parse_index_report(payload)
        except (ValueError, TypeError, IndexError, AttributeError) as e:
            logger.warning("[TwseFetcher] 成交金额（rwd）结构不符预期: %s", e)
            return None

    @staticmethod
    def _latest_trade_value(rows: Any, source: str) -> Optional[Tuple[Optional[datetime.date], float]]:
        if rows is None:
            return None
        if not isinstance(rows, list) or not rows:
            logger.warning("[TwseFetcher] 成交金额（%s）返回结构异常或为空", source)
            return None

        latest = rows[-1]
        if not isinstance(latest, dict):
            logger.warning("[TwseFetcher] 成交金额（%s）最新行结构异常", source)
            return None

        trade_value_yuan = _parse_float(latest.get("TradeValue"))
        if trade_value_yuan <= 0:
            logger.warning("[TwseFetcher] 成交金额（%s）为 0 或无效", source)
            return None

        # TradeValue 单位为「元」，消费方期望「亿」（与 A 股一致：sum/1e8）。
        return _roc_date(latest.get("Date")), trade_value_yuan / 1e8

    def _fetch_institutional(
        self, expected_date: Optional[datetime.date]
    ) -> Optional[Dict[str, float]]:
        """三大法人买卖超（买卖差额），单位转换为「亿新台币」。失败或数据过期返回 None。

        ``expected_date`` 是同一次调用里由 FMTQIK 解析出的最新交易日。BFI82U 会停止
        更新却照样回 200 与结构正确的 JSON（与 ``twtazu_od`` 冻结 79 天同一形状），
        故与 ``_fetch_breadth`` 相同：逐次比对回应自带的 ``date`` 栏（西元 yyyymmdd），
        不符/缺参照一律拒收（fail closed），让字段保持缺失而不是拿旧读数冒充当天。
        """
        try:
            resp = self._session.get(_INSTITUTIONAL_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("[TwseFetcher] 三大法人端点失败: %s", e)
            return None

        if not isinstance(payload, dict):
            logger.warning("[TwseFetcher] 三大法人返回结构异常: 非字典")
            return None

        snapshot_date = _west_date(payload.get("date"))
        if snapshot_date is None:
            logger.warning(
                "[TwseFetcher] 三大法人缺少可解析的 date 栏 (%r)，拒收",
                payload.get("date"),
            )
            return None
        if expected_date is None:
            logger.warning(
                "[TwseFetcher] 无最新交易日参照（成交金额端点失败），无法验证三大法人 "
                "date=%s 是否新鲜，拒收",
                snapshot_date,
            )
            return None
        if snapshot_date != expected_date:
            logger.warning(
                "[TwseFetcher] 三大法人已过期，拒收：date=%s，最新交易日=%s（相差 %d 天）。"
                "端点停止更新时会照样回 200，故一律以日期为准",
                snapshot_date, expected_date, (expected_date - snapshot_date).days,
            )
            return None

        data = payload.get("data")
        if not isinstance(data, list) or not data:
            logger.warning("[TwseFetcher] 三大法人 data 字段缺失或为空")
            return None

        foreign_net = 0.0
        trust_net = 0.0
        dealer_net = 0.0
        total_net = 0.0
        matched = False

        for row in data:
            # 每行: [單位名稱, 買進金額, 賣出金額, 買賣差額]
            if not isinstance(row, (list, tuple)) or len(row) < 4:
                continue
            unit_name = str(row[0]).strip()
            net = _parse_float(row[3]) / 1e8  # 元 -> 亿新台币
            # 注意顺序：「外資及陸資(不含外資自營商)」是市场惯用的外资买卖超主数字；
            # 「外資自營商」是另一行（通常为 0），不可用 startswith("外資") 笼统匹配，
            # 否则后者会覆盖前者，导致 foreign_net 误报为 0。
            if "外資及陸資" in unit_name or "外资及陆资" in unit_name:
                foreign_net = net
                matched = True
            elif unit_name.startswith("外資自營商") or unit_name.startswith("外资自营商"):
                foreign_net += net  # 通常为 0，并入外资合计
                matched = True
            elif unit_name.startswith("投信"):
                trust_net = net
                matched = True
            elif unit_name.startswith("自營商"):
                # 自营商含「自行买卖」与「避险」两行，累加。
                dealer_net += net
                matched = True
            elif unit_name.startswith("合計") or unit_name.startswith("合计"):
                total_net = net
                matched = True

        if not matched:
            logger.warning("[TwseFetcher] 三大法人未匹配到任何已知单位")
            return None

        return {
            "foreign_net": foreign_net,
            "trust_net": trust_net,
            "dealer_net": dealer_net,
            "total_net": total_net,
        }

    def _fetch_tpex_daily(
        self, expected_date: Optional[datetime.date]
    ) -> Optional[Tuple[float, Optional[Dict[str, Any]]]]:
        """上柜成交金额（亿新台币）与柜买指数，同一次 GET、同一道日期比对。

        返回 ``(amount_yi, index)``；失败或数据过期整个返回 None。``index`` 为
        ``{date, close, change, amount}``（amount 单位元，与 ``market_index.turnover``
        一致），指数栏位缺漏或无法解析时为 None，成交金额仍照常返回。

        回应每列带民国 ``Date``（``1150821``）。此端点与 TWSE 侧一样会停止更新却
        照样回 200，故取 ``latest`` 前先比对日期，不符/缺参照拒收（fail closed）；
        成交额与指数共用这一道比对，不会各自放行不同天的读数。
        """
        try:
            resp = self._session.get(_TPEX_TRADE_VALUE_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                logger.warning("[TwseFetcher] 上柜成交金额响应为空")
                return None
            latest = data[-1]  # 取最新一笔
            if not isinstance(latest, dict):
                logger.warning("[TwseFetcher] 上柜成交金额最新行结构异常")
                return None
            snapshot_date = _roc_date(latest.get("Date"))
            if snapshot_date is None:
                logger.warning(
                    "[TwseFetcher] 上柜成交金额缺少可解析的 Date (%r)，拒收",
                    latest.get("Date"),
                )
                return None
            if expected_date is None:
                logger.warning(
                    "[TwseFetcher] 无最新交易日参照，无法验证上柜成交金额 Date=%s "
                    "是否新鲜，拒收",
                    snapshot_date,
                )
                return None
            if snapshot_date != expected_date:
                logger.warning(
                    "[TwseFetcher] 上柜成交金额已过期，拒收：Date=%s，最新交易日=%s"
                    "（相差 %d 天）",
                    snapshot_date, expected_date, (expected_date - snapshot_date).days,
                )
                return None
            amount_yuan = _parse_float(latest.get("TradeAmount"))
            return amount_yuan / 1e8, self._tpex_index_from_row(latest, snapshot_date, amount_yuan)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("[TwseFetcher] 上柜成交金额获取失败: %s", exc)
            return None

    @staticmethod
    def _tpex_index_from_row(
        row: Dict[str, Any], session_date: datetime.date, amount_yuan: float
    ) -> Optional[Dict[str, Any]]:
        """柜买指数读数；``TPExIndex`` / ``Change`` 缺漏或不是有限数字就回 None。

        不用 ``_parse_float``：它把缺值读成 0.0，会把「没资料」变成「平盘 0 点」。
        """
        try:
            close = float(str(row.get("TPExIndex")).replace(",", "").strip())
            change = float(str(row.get("Change")).replace(",", "").strip())
        except (TypeError, ValueError):
            logger.warning(
                "[TwseFetcher] 柜买指数栏位缺漏或无法解析 (TPExIndex=%r, Change=%r)，略过",
                row.get("TPExIndex"), row.get("Change"),
            )
            return None
        if not (math.isfinite(close) and math.isfinite(change)) or close <= 0:
            logger.warning("[TwseFetcher] 柜买指数数值异常 (%r, %r)，略过", close, change)
            return None
        return {
            "date": session_date.isoformat(),
            "close": close,
            "change": change,
            "amount": amount_yuan,
        }

    def _fetch_tpex_institutional(
        self, expected_date: Optional[datetime.date]
    ) -> Optional[Dict[str, float]]:
        """上柜三大法人买卖超净额（亿新台币）。失败或数据过期返回 None。

        每列带民国 ``Date``；正常整包同一天，出现多日混包或无法解析一律拒收。
        """
        try:
            resp = self._session.get(_TPEX_INSTITUTIONAL_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                logger.warning("[TwseFetcher] 上柜三大法人响应为空")
                return None
            snapshot_dates = {
                _roc_date(row.get("Date")) for row in data if isinstance(row, dict)
            }
            if len(snapshot_dates) != 1 or None in snapshot_dates:
                logger.warning(
                    "[TwseFetcher] 上柜三大法人 Date 栏异常 (dates=%s)，拒收",
                    sorted(str(d) for d in snapshot_dates),
                )
                return None
            snapshot_date = snapshot_dates.pop()
            if expected_date is None:
                logger.warning(
                    "[TwseFetcher] 无最新交易日参照，无法验证上柜三大法人 Date=%s "
                    "是否新鲜，拒收",
                    snapshot_date,
                )
                return None
            if snapshot_date != expected_date:
                logger.warning(
                    "[TwseFetcher] 上柜三大法人已过期，拒收：Date=%s，最新交易日=%s"
                    "（相差 %d 天）",
                    snapshot_date, expected_date, (expected_date - snapshot_date).days,
                )
                return None
            foreign_net = trust_net = dealer_net = total_net = 0.0
            matched = False
            for row in data:
                investor = str(row.get("Investor", "")).strip()
                net = _parse_float(row.get("Net")) / 1e8
                # 顶层汇总行（带前导全角空格的为细分子项，跳过避免重复累加）
                if investor == "外資及陸資合計":
                    foreign_net = net
                    matched = True
                elif investor == "投信":
                    trust_net = net
                    matched = True
                elif investor == "自營商合計":
                    dealer_net = net
                    matched = True
                elif investor.startswith("三大法人合計"):
                    total_net = net
                    matched = True
            if not matched:
                logger.warning("[TwseFetcher] 上柜三大法人未匹配到已知单位")
                return None
            return {
                "foreign_net": foreign_net,
                "trust_net": trust_net,
                "dealer_net": dealer_net,
                "total_net": total_net,
            }
        except (requests.RequestException, ValueError) as exc:
            logger.warning("[TwseFetcher] 上柜三大法人获取失败: %s", exc)
            return None

    # --- 对外接口 ---------------------------------------------------------
    def get_market_stats(self) -> Optional[Dict[str, Any]]:
        """
        获取台股上市大盘统计。

        Returns:
            Dict: 成功时包含 6 个标准键（up_count/down_count/flat_count/
                  limit_up_count/limit_down_count/total_amount，total_amount
                  单位为亿新台币），三大法人成功时附加 foreign_net/trust_net/
                  dealer_net/total_net（单位亿新台币）。
                  最新交易日有值时另附 ``trade_date``（ISO 日期字串）：上面所有读数
                  都已对齐到这一天，消费端须拿它与复盘日期比对，不同日就不采用
                  （盘中跑复盘时它是前一个交易日，不是今天）。
                  上柜官方端点日期相符时另附 ``tpex_index``（``{date, close, change,
                  amount}``，amount 单位元；日期与 ``trade_date`` 相同），否则无此键。
            {}:   所有端点均失败时返回空字典（绝不抛出异常）。

        覆盖范围：涨跌家数为 TWSE 上市口径（上柜无公开端点）；成交金额与三大法人
        为上市+上柜合计。降级是**按栏位分组**的：家数、成交金额、三大法人三组各自
        可缺而不影响其余；但成交金额与三大法人这两组各自要求上市与上柜**双边齐全**
        ——单边和会被当成合计读下去，而它可能与合计反向（见下方赋值处的实测数字）。

        涨跌家数有三个可能来源，依序尝试：
        1. TWSE `twtazu_od` 的「股票」列（含涨跌停家数）——**必须通过日期比对**，
           该端点会停止更新却照样回 200；
        2. 上述被拒收时，改用 `MI_INDEX?type=MS` 的「漲跌證券數合計」表「股票」欄
           （含涨跌停家数，回应自带 `date`，须等于最新交易日）；
        3. 仍不可用时，退回 `tw_breadth.closing_breadth()` 由 `market` schema 前复权
           收盘自算（上市普通股，**无涨跌停家数**）。
        两者都不可用时家数保持 0，下游按 truthiness 判成「没有资料」。
        """
        logger.info("[TwseFetcher] 获取台股大盘统计（上市涨跌家数 + 上市/上柜成交额与三大法人）")

        # 上市。成交金额先取，因为它顺带给出 TWSE 自己认定的最新交易日，
        # 而涨跌家数必须拿它当新鲜度参照（见 _fetch_breadth 的 docstring）。
        twse_trade = self._fetch_total_amount()
        latest_trading_date = twse_trade[0] if twse_trade else None
        twse_amount = twse_trade[1] if twse_trade else None
        breadth = self._fetch_breadth(latest_trading_date)
        if breadth is None:
            # twtazu_od 過期／改版：先試 MI_INDEX type=MS（同為「股票」口徑、帶漲跌停、
            # 回應自帶日期），再退回本地宽度。
            breadth = self._fetch_breadth_mi_index(latest_trading_date)
            if breadth is not None:
                logger.info("[TwseFetcher] 涨跌家数改用 MI_INDEX type=MS（含涨跌停家数）")
        if breadth is None and latest_trading_date is not None:
            # 兩支官方端點都不可用時退回 market schema 自己算。**口徑不同**（上市普通股、
            # 無漲跌停家數），差異寫在 data_provider/tw_breadth.py 的 docstring。
            from .tw_breadth import closing_breadth

            breadth = closing_breadth(latest_trading_date)
            if breadth is not None:
                logger.info(
                    "[TwseFetcher] 涨跌家数改用本地 market schema 计算（上市普通股，无涨跌停家数）"
                )
        twse_inst = self._fetch_institutional(latest_trading_date)
        # 上柜（无涨跌家数端点）；成交金额与法人同样以最新交易日当新鲜度参照
        tpex_daily = self._fetch_tpex_daily(latest_trading_date)
        tpex_amount = tpex_daily[0] if tpex_daily else None
        tpex_index = tpex_daily[1] if tpex_daily else None
        tpex_inst = self._fetch_tpex_institutional(latest_trading_date)

        if all(x is None for x in (breadth, twse_amount, twse_inst, tpex_amount, tpex_inst)):
            logger.warning("[TwseFetcher] 所有端点均失败，返回空")
            return {}

        stats: Dict[str, Any] = {
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "total_amount": 0.0,
        }

        # 涨跌家数：仅上市
        if breadth is not None:
            stats.update(breadth)
        else:
            # 家数保持 0 是刻意的：_build_stats_block 的 has_advance_decline 用 truthiness
            # 判定，全 0 会被渲染成「没有资料」而不是「资料是零」。
            logger.warning("[TwseFetcher] 上市涨跌家数缺失或已过期，家数字段保持 0")

        # 成交金额与三大法人都是**上市 + 上柜合计**——栏位名、报告标签、payload 契约
        # 都这么宣称，所以任一边缺就整格作废，绝不拿单边冒充合计。
        #
        # 实测 2026-08-21：上市外资净额 +283.05 亿、上柜 -7.00 亿、合计 +276.05 亿。
        # 单边和会让报告写出「外资卖超 7 亿」——与「买超 276 亿」**方向相反**，而它
        # 是复盘里最常被引用的那个数。成交额单边则是 21%（缺上柜）或 79%（缺上市）
        # 的偏差，LLM 会读成「量能急冻」。
        #
        # 这个「各自可缺、活着的就相加」是既有契约（原本只有网路失败会触发，罕见），
        # 但端点新鲜度检查让它变成常态触发：FMTQIK 通常比 BFI82U 与 TPEx 两支早发布，
        # 于是每天都有一段「上市已更新、上柜还没」的窗口。宁可让
        # `_breadth_availability` 判成没有资料，也不要送一个标签说谎的读数。
        #
        # 想保留单边读数的话，得先给 MarketOverview 加覆盖范围旗标、一路传到 prompt
        # 与报告标签（「上市成交额」而非「两市成交额」），那是另一件事，不在这里偷偷做。
        if twse_amount is not None and tpex_amount is not None:
            stats["total_amount"] = twse_amount + tpex_amount
        else:
            logger.warning(
                "[TwseFetcher] 成交金额覆盖不全（上市%s／上柜%s），total_amount 保持 0.0"
                "——单边和不能冒充上市+上柜合计",
                "有" if twse_amount is not None else "无",
                "有" if tpex_amount is not None else "无",
            )

        if twse_inst is not None and tpex_inst is not None:
            for key in ("foreign_net", "trust_net", "dealer_net", "total_net"):
                stats[key] = twse_inst.get(key, 0.0) + tpex_inst.get(key, 0.0)
        else:
            logger.warning(
                "[TwseFetcher] 三大法人覆盖不全（上市%s／上柜%s），省略法人字段"
                "——单边净额与合计可能反向（实测上市 +283 亿 vs 上柜 -7 亿）",
                "有" if twse_inst is not None else "无",
                "有" if tpex_inst is not None else "无",
            )

        # 櫃買指數：與上柜成交额同一次 GET、同一道日期比对，所以日期必为 trade_date。
        if tpex_index is not None:
            stats["tpex_index"] = tpex_index

        # 場次日期：消費端（market_analyzer）靠它判斷這批數字是不是複盤那一天的。
        # 拿不到 TWSE 認定的最新交易日就不寫——消費端對缺鍵一律拒收。
        if latest_trading_date is not None:
            stats["trade_date"] = latest_trading_date.isoformat()

        logger.info(
            "[TwseFetcher] 统计完成 up=%s down=%s amount=%.0f亿(上市%s+上柜%s) "
            "institutional=上市%s/上柜%s",
            stats["up_count"],
            stats["down_count"],
            stats["total_amount"],
            "有" if twse_amount is not None else "无",
            "有" if tpex_amount is not None else "无",
            "有" if twse_inst is not None else "无",
            "有" if tpex_inst is not None else "无",
        )
        return stats
