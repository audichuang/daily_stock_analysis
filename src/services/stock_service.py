# -*- coding: utf-8 -*-
"""
===================================
股票数据服务层
===================================

职责：
1. 封装股票数据获取逻辑
2. 提供实时行情和历史数据接口
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from src.repositories.stock_repo import StockRepository

logger = logging.getLogger(__name__)


def _map_quote_to_dict(quote: Any, fallback_code: str) -> Dict[str, Any]:
    """把 UnifiedRealtimeQuote 映射为 API 友好的 dict（单股/批次共用）。

    全部用 getattr 安全访问，缺失字段为 None；新增 source/as_of/is_stale 用于
    诚实标示行情来源与时效（台股 yfinance 约延迟 15-20 分钟）。
    """
    src = getattr(quote, "source", None)
    return {
        "stock_code": getattr(quote, "code", fallback_code),
        "stock_name": getattr(quote, "name", None),
        "current_price": getattr(quote, "price", 0.0) or 0.0,
        "change": getattr(quote, "change_amount", None),
        "change_percent": getattr(quote, "change_pct", None),
        "open": getattr(quote, "open_price", None),
        "high": getattr(quote, "high", None),
        "low": getattr(quote, "low", None),
        "prev_close": getattr(quote, "pre_close", None),
        "volume": getattr(quote, "volume", None),
        "amount": getattr(quote, "amount", None),
        "update_time": datetime.now().isoformat(),
        # provider_timestamp 优先（真实行情时间），否则退回 fetched_at（本系统获取时间）
        "as_of": getattr(quote, "provider_timestamp", None) or getattr(quote, "fetched_at", None),
        "source": src.value if src is not None else None,
        "is_stale": getattr(quote, "is_stale", None),
    }


class StockService:
    """
    股票数据服务
    
    封装股票数据获取的业务逻辑
    """
    
    def __init__(self):
        """初始化股票数据服务"""
        self.repo = StockRepository()
    
    def get_realtime_quote(
        self, stock_code: str, *, manager: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取股票实时行情

        Args:
            stock_code: 股票代码
            manager: 可选，复用已建好的 DataFetcherManager（批次场景）；None 时自建

        Returns:
            实时行情数据字典
        """
        try:
            own_manager = manager is None
            if own_manager:
                from data_provider.base import DataFetcherManager

                manager = DataFetcherManager()
            try:
                quote = manager.get_realtime_quote(stock_code)
            finally:
                if own_manager and hasattr(manager, "close"):
                    manager.close()

            if quote is None:
                logger.warning(f"获取 {stock_code} 实时行情失败")
                return None

            return _map_quote_to_dict(quote, stock_code)

        except ImportError:
            logger.warning("DataFetcherManager 未找到，使用占位数据")
            return self._get_placeholder_quote(stock_code)
        except Exception as e:
            logger.error(f"获取实时行情失败: {e}", exc_info=True)
            return None

    def get_realtime_quotes(self, codes: List[str]) -> List[Optional[Dict[str, Any]]]:
        """批量获取实时行情（看板用）。

        建一个 DataFetcherManager 复用全程；逐个取价，单个失败回 None（不拖垮整批）。
        返回与 codes 等长、同序的列表，元素为 dict 或 None。

        ponytail: sequential 迴圈即可（30s 輪詢 + watchlist 量級）；
        台股 Shioaji 是模組級單一 session（序列化瓶頸），盲目併發無益。
        watchlist 變大且實測偏慢時，再上 bounded ThreadPoolExecutor。
        """
        from data_provider.base import DataFetcherManager

        manager = DataFetcherManager()
        results: List[Optional[Dict[str, Any]]] = []
        try:
            for code in codes:
                try:
                    quote = manager.get_realtime_quote(code, log_final_failure=False)
                    results.append(_map_quote_to_dict(quote, code) if quote is not None else None)
                except Exception as e:  # 单个代码失败不影响其余
                    logger.warning(f"批量行情: {code} 取价失败: {e}")
                    results.append(None)
        finally:
            if hasattr(manager, "close"):
                manager.close()
        return results
    
    def get_history_data(
        self,
        stock_code: str,
        period: str = "daily",
        days: int = 30
    ) -> Dict[str, Any]:
        """
        获取股票历史行情
        
        Args:
            stock_code: 股票代码
            period: K 线周期 (daily/weekly/monthly)
            days: 获取天数
            
        Returns:
            历史行情数据字典
            
        Raises:
            ValueError: 当 period 不是 daily 时抛出（weekly/monthly 暂未实现）
        """
        # 验证 period 参数，只支持 daily
        if period != "daily":
            raise ValueError(
                f"暂不支持 '{period}' 周期，目前仅支持 'daily'。"
                "weekly/monthly 聚合功能将在后续版本实现。"
            )
        
        try:
            # 调用数据获取器获取历史数据
            from data_provider.base import DataFetcherManager
            
            manager = DataFetcherManager()
            df, source = manager.get_daily_data(stock_code, days=days)
            
            if df is None or df.empty:
                logger.warning(f"获取 {stock_code} 历史数据失败")
                return {"stock_code": stock_code, "period": period, "data": []}
            
            # 获取股票名称
            stock_name = manager.get_stock_name(stock_code)
            
            # 转换为响应格式
            data = []
            for _, row in df.iterrows():
                date_val = row.get("date")
                if hasattr(date_val, "strftime"):
                    date_str = date_val.strftime("%Y-%m-%d")
                else:
                    date_str = str(date_val)
                
                data.append({
                    "date": date_str,
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", 0)) if row.get("volume") else None,
                    "amount": float(row.get("amount", 0)) if row.get("amount") else None,
                    "change_percent": float(row.get("pct_chg", 0)) if row.get("pct_chg") else None,
                })
            
            return {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "period": period,
                "data": data,
            }
            
        except ImportError:
            logger.warning("DataFetcherManager 未找到，返回空数据")
            return {"stock_code": stock_code, "period": period, "data": []}
        except Exception as e:
            logger.error(f"获取历史数据失败: {e}", exc_info=True)
            return {"stock_code": stock_code, "period": period, "data": []}
    
    def _get_placeholder_quote(self, stock_code: str) -> Dict[str, Any]:
        """
        获取占位行情数据（用于测试）
        
        Args:
            stock_code: 股票代码
            
        Returns:
            占位行情数据
        """
        return {
            "stock_code": stock_code,
            "stock_name": f"股票{stock_code}",
            "current_price": 0.0,
            "change": None,
            "change_percent": None,
            "open": None,
            "high": None,
            "low": None,
            "prev_close": None,
            "volume": None,
            "amount": None,
            "update_time": datetime.now().isoformat(),
            "source": "placeholder",
            "as_of": None,
            "is_stale": None,
        }
