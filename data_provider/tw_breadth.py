# -*- coding: utf-8 -*-
"""上市普通股的收盤漲跌家數，從 `market` schema 自己算。

存在的理由：TWSE 的 `opendata/twtazu_od`（漲跌家數）會停止更新卻照樣回 HTTP 200
（2026-08 實測凍結 79 天），`TwseFetcher._fetch_breadth` 現在會以日期比對拒收過期
快照——拒收之後大盤複盤就完全沒有寬度資料。本模組補那一格。

**與被取代的端點的口徑差異**（引用數字時必須知道）：

| | TWSE `twtazu_od`「股票」列 | 本模組 |
| --- | --- | --- |
| 範圍 | 上市（含特別股等） | 上市普通股（`stock_info` ∩ `is_common_stock`） |
| 基準 | 官方參考價（除權息已還原） | 前復權收盤（`price_adjustment`，等效） |
| 漲停/跌停 | 有 | **無**（見下） |

`price.market` 全欄為 NULL（TWSE/TPEx 在爬取端已合併，無法逐列區分上市/上櫃），
所以上市口徑只能靠 `market.stock_info` 取——它只含上市約 1,095 檔。

**刻意不提供漲跌停家數**：判定漲跌停要當日官方參考價與 ±10% 規則，而 ETF/ETN 不受
漲跌幅限制、興櫃與新上市前五日也無限制。用「日變動 ≥ ±9.5%」代理算出來的數量級與
官方對不上（實測 2026-07-31 官方 64 檔、代理 217 檔），寧可留空讓
`_build_stats_block` 的 `has_limit` 判成缺資料，也不要送一個看起來像官方數的近似值。
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 算漲跌需要前一交易日；多取幾根是為了讓 `factors_to_panel` 的累乘在窗口內成形，
# 並容忍個股當日無成交（那種列會是 NaN，計數時自然被排除＝無比價）。
_WINDOW_SESSIONS = 15

# 本地 DB 讀取逾時（毫秒）。DB 被鎖或查詢失控時，讓寬度計算失敗降級（回 None），
# 而不是把整個大盤統計卡住。
_STATEMENT_TIMEOUT_MS = 5000

# 浮點誤差容忍：台股最小跳動 0.01 元，1e-9 遠小於它，只用來吸收 float 乘法誤差。
_FLAT_EPS = 1e-9


def count_advance_decline(today, prev) -> Optional[Dict[str, int]]:
    """兩組（已前復權的）收盤價 → 漲跌平家數。純函式，不碰 DB。

    任一日缺價（NaN）視為**無比價**而排除，不當成平盤——那正是 TWSE 官方
    `無比價` 那一欄的語意，把它算進平盤會虛增分母。
    """
    delta = (today - prev).dropna()
    if delta.empty:
        return None
    up = int((delta > _FLAT_EPS).sum())
    down = int((delta < -_FLAT_EPS).sum())
    return {"up_count": up, "down_count": down,
            "flat_count": int(len(delta) - up - down)}


def closing_breadth(trading_date, engine=None) -> Optional[Dict[str, Any]]:
    """回傳 ``{"up_count", "down_count", "flat_count"}``，無法可信計算時回 None。

    ``trading_date`` 是呼叫端已確認的最新交易日（``datetime.date``）。**必須逐次比對**：
    `market.price` 也會停更（cron 掛掉、TWSE 封 IP 都是靜默的，見 market_data/AGENTS.md），
    拿它的最後一天當「今天」等於重犯 twtazu_od 那個錯。

    任何失敗（缺 `DATABASE_URL`、DB 不可達、資料不夠、日期不符）都回 None 讓呼叫端降級，
    絕不抛出——大盤複盤不該因為寬度這一格掛掉。
    """
    try:
        import pandas as pd
        from sqlalchemy import text

        from market_data import adjust
        from market_data.adjust import is_common_stock
        from market_data.db import get_engine
    except Exception as exc:  # 缺相依（面板 venv 沒裝 psycopg 等）
        logger.warning("[TwBreadth] 相依不可用，跳過本地寬度計算: %s", exc)
        return None

    try:
        eng = engine or get_engine(statement_timeout_ms=_STATEMENT_TIMEOUT_MS)
        # 只取上市：price.market 全為 NULL，唯一的上市名單是 stock_info。
        px = pd.read_sql(
            text(
                "select p.stock_id, p.date, p.close from market.price p "
                "join market.stock_info s on s.stock_id = p.stock_id "
                "where p.date > (select max(date) from market.price) "
                f"                - interval '{_WINDOW_SESSIONS * 2} days'"
            ),
            eng,
            parse_dates=["date"],
        )
    except Exception as exc:
        logger.warning("[TwBreadth] 讀取 market.price 失敗，跳過本地寬度計算: %s", exc)
        return None

    if px.empty:
        logger.warning("[TwBreadth] market.price 查無資料，跳過本地寬度計算")
        return None

    px = px[px["stock_id"].map(is_common_stock)]
    if px.empty:
        logger.warning("[TwBreadth] 過濾普通股後無資料，跳過本地寬度計算")
        return None

    closes = px.pivot(index="date", columns="stock_id", values="close").sort_index()
    closes = closes.astype(float)
    if len(closes.index) < 2:
        logger.warning("[TwBreadth] market.price 不足兩個交易日，無法算漲跌")
        return None

    db_latest = closes.index[-1].date()
    if db_latest != trading_date:
        logger.warning(
            "[TwBreadth] market.price 最後交易日=%s 與最新交易日=%s 不符，"
            "拒絕用舊資料當今日寬度（先跑 `market_data.cli daily` 補資料）",
            db_latest, trading_date,
        )
        return None

    # 前復權：除權息當天的價格斷崖不是下跌。官方漲跌家數比的是參考價，等效於此。
    # 因子讀取失敗（含逾時）也要降級回 None——「絕不抛出」的承諾涵蓋這一步，否則例外會
    # 穿過 TwseFetcher.get_market_stats，連已抓好的成交額與法人一起丟掉。
    try:
        closes = closes * adjust.load_factors(
            eng, closes.index, closes.columns, start=closes.index[0])
    except Exception as exc:
        logger.warning("[TwBreadth] 讀取 price_adjustment 失敗，跳過本地寬度計算: %s", exc)
        return None

    counts = count_advance_decline(closes.iloc[-1], closes.iloc[-2])
    if counts is None:
        logger.warning("[TwBreadth] 無可比價的個股，跳過本地寬度計算")
        return None

    logger.info(
        "[TwBreadth] 本地寬度（上市普通股 %d 檔，前復權，%s vs %s）：漲 %d / 跌 %d / 平 %d",
        sum(counts.values()), db_latest, closes.index[-2].date(),
        counts["up_count"], counts["down_count"], counts["flat_count"],
    )
    return counts
