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
2. 大盘指数（^TWII / ^TWOII）由 YfinanceFetcher 提供，本数据源不返回指数。
3. 每个端点独立 try/except，部分降级：若三大法人失败但涨跌家数成功，
   仍返回涨跌家数并省略法人字段；全部失败才返回 {}，绝不向上抛出异常。
"""

import logging
from typing import Optional, Dict, Any

import pandas as pd
import requests

from .base import BaseFetcher

logger = logging.getLogger(__name__)

# TWSE 上市 免金钥端点
_BREADTH_URL = "https://openapi.twse.com.tw/v1/opendata/twtazu_od"          # 涨跌家数
_INSTITUTIONAL_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"  # 三大法人买卖超
_TRADE_VALUE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"   # 成交金额 + 加权指数

# TPEx 上柜 免金钥 OpenAPI 端点（上柜无公开「涨跌家数」端点，故仅补成交金额与三大法人）
_TPEX_TRADE_VALUE_URL = "https://www.tpex.org.tw/openapi/v1/tpex_daily_trading_index"  # 上柜成交金额 + 柜买指数
_TPEX_INSTITUTIONAL_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_summary"     # 上柜三大法人买卖超彙总

# (connect timeout, read timeout)
_TIMEOUT = (5, 10)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


def _parse_int(value: Any) -> int:
    """将可能含千分位逗号的字符串解析为 int；失败返回 0。"""
    if value is None:
        return 0
    text = str(value).replace(",", "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return 0


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
    def _fetch_breadth(self) -> Optional[Dict[str, int]]:
        """涨跌家数（整体市场）。返回 5 个家数键，失败返回 None。"""
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

        target = None
        for row in rows:
            if isinstance(row, dict) and row.get("類型") == "整體市場":
                target = row
                break
        if target is None:
            logger.warning("[TwseFetcher] 涨跌家数未找到「整體市場」行")
            return None

        return {
            "up_count": _parse_int(target.get("上漲")),
            "down_count": _parse_int(target.get("下跌")),
            "flat_count": _parse_int(target.get("持平")),
            "limit_up_count": _parse_int(target.get("漲停")),
            "limit_down_count": _parse_int(target.get("跌停")),
        }

    def _fetch_total_amount(self) -> Optional[float]:
        """成交金额（最新交易日），单位转换为「亿新台币」。失败返回 None。"""
        try:
            resp = self._session.get(_TRADE_VALUE_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            rows = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("[TwseFetcher] 成交金额端点失败: %s", e)
            return None

        if not isinstance(rows, list) or not rows:
            logger.warning("[TwseFetcher] 成交金额返回结构异常或为空")
            return None

        latest = rows[-1]
        if not isinstance(latest, dict):
            logger.warning("[TwseFetcher] 成交金额最新行结构异常")
            return None

        trade_value_yuan = _parse_float(latest.get("TradeValue"))
        if trade_value_yuan <= 0:
            logger.warning("[TwseFetcher] 成交金额为 0 或无效")
            return None

        # TradeValue 单位为「元」，消费方期望「亿」（与 A 股一致：sum/1e8）。
        return trade_value_yuan / 1e8

    def _fetch_institutional(self) -> Optional[Dict[str, float]]:
        """三大法人买卖超（买卖差额），单位转换为「亿新台币」。失败返回 None。"""
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

    def _fetch_tpex_total_amount(self) -> Optional[float]:
        """上柜成交金额（亿新台币）。失败返回 None。"""
        try:
            resp = self._session.get(_TPEX_TRADE_VALUE_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                logger.warning("[TwseFetcher] 上柜成交金额响应为空")
                return None
            latest = data[-1]  # 取最新一笔
            amount_yuan = _parse_float(latest.get("TradeAmount"))
            return amount_yuan / 1e8
        except (requests.RequestException, ValueError) as exc:
            logger.warning("[TwseFetcher] 上柜成交金额获取失败: %s", exc)
            return None

    def _fetch_tpex_institutional(self) -> Optional[Dict[str, float]]:
        """上柜三大法人买卖超净额（亿新台币）。失败返回 None。"""
        try:
            resp = self._session.get(_TPEX_INSTITUTIONAL_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                logger.warning("[TwseFetcher] 上柜三大法人响应为空")
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
            {}:   所有端点均失败时返回空字典（绝不抛出异常）。

        覆盖范围：涨跌家数为 TWSE 上市口径（上柜无公开端点）；成交金额与三大法人
        为上市+上柜合计。任一来源失败均部分降级，不影响其余字段。
        """
        logger.info("[TwseFetcher] 获取台股大盘统计（上市涨跌家数 + 上市/上柜成交额与三大法人）")

        # 上市
        breadth = self._fetch_breadth()
        twse_amount = self._fetch_total_amount()
        twse_inst = self._fetch_institutional()
        # 上柜（无涨跌家数端点）
        tpex_amount = self._fetch_tpex_total_amount()
        tpex_inst = self._fetch_tpex_institutional()

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
            logger.warning("[TwseFetcher] 上市涨跌家数缺失，家数字段保持 0")

        # 成交金额：上市 + 上柜（各自可缺）
        amount_parts = [a for a in (twse_amount, tpex_amount) if a is not None]
        if amount_parts:
            stats["total_amount"] = sum(amount_parts)
        else:
            logger.warning("[TwseFetcher] 上市/上柜成交金额均缺失，total_amount 保持 0.0")

        # 三大法人：上市 + 上柜逐项相加（各自可缺）
        inst_parts = [i for i in (twse_inst, tpex_inst) if i is not None]
        if inst_parts:
            for key in ("foreign_net", "trust_net", "dealer_net", "total_net"):
                stats[key] = sum(part.get(key, 0.0) for part in inst_parts)
        else:
            logger.warning("[TwseFetcher] 上市/上柜三大法人均缺失，省略法人字段（部分降级）")

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
