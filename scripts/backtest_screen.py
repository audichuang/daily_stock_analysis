#!/usr/bin/env python3
"""screen_tw 選股策略的事件驅動回測（market schema，離線）。

回測的價值取決於有沒有作弊，所以三個防前視偏誤的處理都寫死在這裡：

1. **訊號在 T 日收盤後產生，成交在 T+1 開盤**。不用 T 日收盤價成交。
2. **法人／PE 資料 lag 1 個交易日**。market_data 的 cron 15:00 跑，當日法人常要 T+1 才補齊
   （見 market_data/AGENTS.md），T 日盤後就用 T 日法人資料屬於未來資訊。
3. **全部價格前復權**。台股 6–8 月是除權息旺季（2026 年 6 月 272 檔、7 月 373 檔）；
   不還原的話除息跳空會被當成下跌、大量誤觸停損，同時漏計股息收益。

資料覆蓋限制（決定樣本能拉多長）：
  - `market.valuation` 只有 2026-07 之後 → 估值因子改用 `market.price.pe_ratio`（覆蓋約 57%）
  - `market.institutional` 自 2012-05 起，每日覆蓋 880~1340 檔（偏大型股）
  - 故預設樣本自 2013-01-01 起。

用法：
    uv run --env-file .env python scripts/backtest_screen.py --all-exits
    uv run --env-file .env python scripts/backtest_screen.py --start 2013-01-01 --end 2026-07-24
    uv run --env-file .env python scripts/backtest_screen.py --exclude-industry 03 --by-year
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data.adjust import load_factors  # noqa: E402
from market_data.db import get_engine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# --- 台股交易成本（逐筆從現金扣，不是事後從報酬減）---
# 先前的實作只把成本記在交易明細的 ret 欄，沒有從 cash 扣，淨值曲線因此系統性高估：
# 以每年 6.6 個資金輪次計高估約 3.9%/年，高頻規則（hold5 每年 39 輪）高估逾 22%/年。
FEE_RATE = 0.001425      # 券商手續費，買賣各一次（--fee-discount 可打折）
MIN_FEE = 20             # 單筆最低手續費（元）——小額交易的實際成本遠高於費率
TAX_RATE = 0.003         # 證交稅，僅賣出時課
SLIPPAGE = 0.0015        # 單邊滑價
# 二代健保補充保費 2.11%（單筆股利 ≥ 20,000 元）課的是**股利所得**，不是交易稅。
# 本回測用前復權價（total return），股息已隱含在價格裡、無法逐筆分離，故未扣。
# 這對策略與 0050 基準是同方向的高估，比較上大致抵銷；要精確處理需分離股息現金流。
TRADING_DAYS = 252

# 出場規則以參數字典描述，避免十幾個 if 分支各寫一遍。
#   ma / atr_buffer : 收盤跌破 MA(n) - buffer×ATR
#   grace           : 進場後 N 日內不觸發均線出場（避開買在門檻上的 whipsaw）
#   trail           : 自持有期間收盤最高點回落 N%
#   chandelier      : 自持有期間收盤最高點回落 N×ATR（吊燈停損）
#   stop / take     : 相對進場價的固定停損／停利
#   hold            : 固定持有 N 個交易日
EXIT_RULES = {
    "none": {},
    "ma10": {"ma": 10},
    "ma20": {"ma": 20},
    "ma60": {"ma": 60},
    "ma20_atr1": {"ma": 20, "atr_buffer": 1.0},
    "ma20_atr2": {"ma": 20, "atr_buffer": 2.0},
    "ma20_grace5": {"ma": 20, "grace": 5},
    "trail10": {"trail": 0.10},
    "trail15": {"trail": 0.15},
    "trail20": {"trail": 0.20},
    "chandelier3": {"chandelier": 3.0},
    "stop8": {"stop": 0.08},
    "stop8_take20": {"stop": 0.08, "take": 0.20},
    "stop8_take30": {"stop": 0.08, "take": 0.30},
    "hold5": {"hold": 5},
    "hold10": {"hold": 10},
    "hold20": {"hold": 20},
    "hold60": {"hold": 60},
}


def load_panel(engine, start, end):
    """拉回測期資料並前復權。回傳寬表面板（index=date, columns=stock_id）。

    前復權因子讀 ``market.price_adjustment``（除權息 + 減資 + 分割，見 market_data/adjust.py）。
    不要改回直接讀 ``ex_dividend``——那張表缺上櫃除權息、分割與減資，0050 的 1:4 分割會讓
    基準在 2025 年顯示 -65.79%。表是空的就先跑 ``market_data.cli adjust``。
    """
    # 400 天暖機（約 270 個交易日）：MA200 的 regime 閘門要有完整均線才不會在樣本
    # 前段整段變成 False（比較短的 MA60/MA20 用 200 天就夠）。
    hist_start = (pd.Timestamp(start) - pd.Timedelta(days=400)).date()
    with engine.connect() as c:
        px = pd.read_sql(text(
            "select stock_id, date, open, high, low, close, turnover, pe_ratio from market.price "
            "where date between :s and :e"
        ), c, params={"s": hist_start, "e": end}, parse_dates=["date"])
        inst = pd.read_sql(text(
            "select stock_id, date, foreign_net, trust_net, dealer_net from market.institutional "
            "where date between :s and :e"
        ), c, params={"s": hist_start, "e": end}, parse_dates=["date"])
        val = pd.read_sql(text(
            "select stock_id, date, pb_ratio, dividend_yield from market.valuation "
            "where date between :s and :e"
        ), c, params={"s": hist_start, "e": end}, parse_dates=["date"])
        # 用 announce_date 而非 revenue_month 對齊——營收在次月 10 日前才公布，
        # 用所屬月份會讓策略提前看到還沒發布的數字。
        rev = pd.read_sql(text(
            "select stock_id, announce_date as date, yoy from market.monthly_revenue "
            "where announce_date between :s and :e and yoy is not null"
        ), c, params={"s": hist_start, "e": end}, parse_dates=["date"])
    for col in ("open", "high", "low", "close", "turnover", "pe_ratio"):
        px[col] = px[col].astype(float)

    piv = {k: px.pivot(index="date", columns="stock_id", values=k).sort_index()
           for k in ("open", "high", "low", "close", "turnover", "pe_ratio")}
    adj = load_factors(engine, piv["close"].index, piv["close"].columns)
    # **缺前復權要 fail-fast，不能只印 WARN**：未還原的價格會讓除息跳空被當成真實下跌
    # （0050 的 1:4 分割曾讓基準顯示 -65.79%；上櫃除息未還原造成約 20pp/年的偏差），
    # 而一份印了 WARN 但照樣輸出的績效表，看起來與正確的沒有兩樣。
    covered = (adj != 1.0).any().sum()
    if covered < 0.2 * adj.shape[1]:
        raise RuntimeError(
            f"price_adjustment 只覆蓋 {covered}/{adj.shape[1]} 檔（門檻 20%），"
            f"價格幾乎未還原，拒絕產出績效數字。先跑 "
            f"`uv run --env-file .env python -m market_data.cli adjust`。")
    for k in ("open", "high", "low", "close"):
        piv[k] = piv[k] * adj
    return piv, inst, val, rev


def build_indicators(close, turnover, inst, pe, high=None, low=None, lag_days=1,
                     val=None, rev=None):
    """向量化算全面板指標。法人／估值／營收一律 shift(lag_days) 避免用到尚未發布的資料。"""
    ind = {
        "close": close,
        "ma10": close.rolling(10).mean(),
        "ma20": close.rolling(20).mean(),
        "ma60": close.rolling(60).mean(),
        "d1": close.pct_change(1),
        "d20": close.pct_change(20),
        "d60": close.pct_change(60),
        "turnover20": turnover.rolling(20).mean(),
        "vol20": close.pct_change().rolling(20).std(),
    }
    ind["bias20"] = close / ind["ma20"] - 1

    if high is not None and low is not None:
        prev = close.shift(1)
        tr = np.maximum(high - low, np.maximum((high - prev).abs(), (low - prev).abs()))
        ind["atr"] = tr.rolling(14).mean()
    else:
        ind["atr"] = close * 0.02  # 無高低價時的粗略替代，僅供單元測試

    for c in ("foreign_net", "trust_net", "dealer_net"):
        inst[c] = inst[c].astype(float)
    inst["ft"] = inst["foreign_net"] + inst["trust_net"] + inst["dealer_net"]
    # institutional / pe 覆蓋的標的少於 price，一律對齊到 close 的欄位再算
    ft = (inst.pivot_table(index="date", columns="stock_id", values="ft")
          .reindex(index=close.index, columns=close.columns).fillna(0))
    ind["inst5"] = ft.rolling(5).sum().shift(lag_days)
    ind["inst20"] = ft.rolling(20).sum().shift(lag_days)
    # PE 的 ffill **必須有保鮮期**，理由與下面 `_pit` 的 stale_days 完全相同：公司由獲利
    # 轉虧後 pe_ratio 開始為 NULL，無上限 ffill 會讓最後一個正 PE 沿用數月甚至數年，
    # 繼續參與 momentum/value 的排名。PB 與殖利率早就有上限，PE 先前漏了。
    ind["pe"] = (pe.reindex(index=close.index, columns=close.columns)
                 .ffill(limit=10).shift(lag_days))

    def _pit(df, col, stale_days):
        """point-in-time 對齊：公布日之後才看得到，ffill 但**有保鮮期**。

        兩個容易錯的地方：
        1. 公告日常落在非交易日，直接 `reindex` 到交易日會把那些列**整筆刪掉**而不是
           順延——實測 185,202 筆月營收有 52,288 筆（28.2%）的 announce_date 在週末，
           全部會消失。故先用 `merge_asof(direction="forward")` 映射到下一個交易日。
        2. `stale_days` 不可省。valuation 歷史有缺口，無上限的 ffill 會把 2020 年初的
           PB 一路延用到 2026 年——訊號數看起來正常但值是過期的，比沒訊號更危險。
        """
        if df is None or not len(df):
            return pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        cal = pd.DataFrame({"date": close.index}).sort_values("date")
        mapped = pd.merge_asof(
            df[["date", "stock_id", col]].sort_values("date"),
            cal.rename(columns={"date": "eff"}),
            left_on="date", right_on="eff", direction="forward",
        ).dropna(subset=["eff"])
        p = mapped.pivot_table(index="eff", columns="stock_id", values=col)
        p = p.reindex(index=close.index, columns=close.columns).ffill(limit=stale_days)
        return p.shift(lag_days)

    ind["pb"] = _pit(val, "pb_ratio", 10)        # 估值每交易日更新
    ind["divy"] = _pit(val, "dividend_yield", 10)
    ind["rev_yoy"] = _pit(rev, "yoy", 45)        # 月營收每月公布一次
    return ind


# 進場因子：每個定義 (額外篩選, 排序分數)。所有因子共用同一組基礎門檻（流動性 + 有價），
# 只換選股邏輯，這樣比較的才是因子本身而非門檻差異。
# 出場規則能改善的幅度有限（實測最差到最好差 24pp 但終點仍為負），瓶頸在這裡。
FACTORS = {
    # 現況：價格動能 + 法人買超 + 低乖離 + 低 PE，須多頭排列
    "momentum": {
        "filter": lambda a: (a("close") > a("ma20")) & (a("ma20") > a("ma60")) & (a("inst5") > 0),
        "score": lambda r, f: (r["d20"] + r["inst5"] + r["d1"] * 0.8
                               + (1 - r["bias20"]) * 0.5 + (1 - r["pe_c"]) * 0.5),
    },
    # 純價格動能（12-1 動量的短版），不看籌碼
    "pure_momentum": {
        "filter": lambda a: a("d60").notna(),
        "score": lambda r, f: r["d60"] + r["d20"] * 0.5,
    },
    # 營收動能：月營收 YoY（用 announce_date 對齊，僅上市有值）
    "revenue": {
        "filter": lambda a: a("rev_yoy").notna() & (a("close") > a("ma60")),
        "score": lambda r, f: r["rev_yoy"] + r["d20"] * 0.3,
    },
    # 低波動：台股與多數市場都有的低波動溢酬
    "lowvol": {
        "filter": lambda a: a("vol20").notna() & (a("close") > a("ma60")),
        "score": lambda r, f: (1 - r["vol20"]),
    },
    # 價值：低 PB + 高殖利率 + 低 PE（需 valuation 歷史）
    "value": {
        "filter": lambda a: (a("pb") > 0) & (a("pb") < 3) & (a("divy") > 0),
        "score": lambda r, f: (1 - r["pb"]) + r["divy"] + (1 - r["pe_c"]) * 0.5,
    },
    # 價值 + 動能：便宜且已經在漲（避開價值陷阱）
    "value_momentum": {
        "filter": lambda a: (a("pb") > 0) & (a("pb") < 3) & (a("close") > a("ma60")),
        "score": lambda r, f: (1 - r["pb"]) + r["d20"] + r["divy"] * 0.5,
    },
    # 純法人買超
    "inst": {
        "filter": lambda a: a("inst20") > 0,
        "score": lambda r, f: r["inst20"] + r["inst5"] * 0.5,
    },
    # 營收動能 + 低波動：revenue 的選股力配 lowvol 的回撤（-21.7% vs -51.6%）。
    # 波動門檻取當日**橫斷面中位數**而非固定值——固定值在 2020 這種高波動年會篩掉全部。
    "revenue_lowvol": {
        "filter": lambda a: (a("rev_yoy").notna() & (a("close") > a("ma60"))
                             & (a("vol20") < a("vol20").median())),
        "score": lambda r, f: r["rev_yoy"] + (1 - r["vol20"]) * 0.5,
    },
    # 營收動能 + 價格動能：基本面轉強且價格已確認（多頭排列）
    "revenue_momentum": {
        "filter": lambda a: (a("rev_yoy").notna() & (a("close") > a("ma20"))
                             & (a("ma20") > a("ma60"))),
        "score": lambda r, f: r["rev_yoy"] + r["d20"] * 0.5,
    },
    # 對照組:同一組基礎門檻(流動性+有價)下純隨機選股。存在的理由是「+15% 超額到底是
    # 選股力還是運氣」只能靠虛無分布回答——用 --null-trials 跑 N 次取分布,真因子若落在
    # 隨機分布裡面就是噪音。不要拿它當策略。
    "random": {
        "filter": lambda a: a("close").notna(),
        "score": lambda r, f: pd.Series(np.random.rand(len(f)), index=f.index),
    },
}
_SCORE_COLS = ("d1", "d20", "d60", "inst5", "inst20", "bias20", "pe", "vol20", "pb", "divy", "rev_yoy")


def signals_on(ind, day, min_turnover, top_n, factor="momentum"):
    """跑選股漏斗 + 排序，只用 <= day 的資料。回傳 top_n 個 stock_id。"""
    def at(k):
        return ind[k].loc[day]

    spec = FACTORS[factor]
    ok = (at("turnover20") >= min_turnover) & at("close").notna() & spec["filter"](at)
    ok = ok.fillna(False)
    if not ok.any():
        return []
    cand = ok[ok].index
    f = pd.DataFrame({k: ind[k].loc[day, cand] for k in _SCORE_COLS})
    r = f.rank(pct=True)
    # PE 要剔除異常值再排名（負值與 >100 多為一次性損益，不代表貴或便宜）
    r["pe_c"] = f["pe"].where(f["pe"].between(0, 100)).fillna(f["pe"].median()).rank(pct=True)
    score = spec["score"](r, f).dropna()
    if score.empty:
        return []
    return list(score.sort_values(ascending=False).head(top_n).index)


def precompute_signals(ind, days, min_turnover, top_n, etf_mask, factor="momentum"):
    """訊號與出場規則無關，先算一次讓所有規則共用（否則 N 個規則要重算 N 遍）。"""
    out = {}
    for day in days:
        picks = signals_on(ind, day, min_turnover, top_n * 3, factor)
        out[day] = [s for s in picks if not etf_mask.get(s, False)][:top_n]
    return out


def should_exit(ind, sid, day, pos, cfg, max_hold):
    """回傳 (是否出場, 原因)。全部用收盤價判斷，實際成交在隔日開盤。"""
    c = ind["close"].at[day, sid]
    if pd.isna(c):
        return False, ""
    held, entry, peak = pos["held"], pos["entry_price"], pos["peak"]

    if "hold" in cfg:
        return (held >= cfg["hold"]), f"持滿{cfg['hold']}日"
    if "stop" in cfg and c <= entry * (1 - cfg["stop"]):
        return True, f"停損-{cfg['stop'] * 100:.0f}%"
    if "take" in cfg and c >= entry * (1 + cfg["take"]):
        return True, f"停利+{cfg['take'] * 100:.0f}%"
    if "trail" in cfg and c <= peak * (1 - cfg["trail"]):
        return True, f"回落{cfg['trail'] * 100:.0f}%"
    if "chandelier" in cfg:
        atr = ind["atr"].at[day, sid]
        if pd.notna(atr) and c <= peak - cfg["chandelier"] * atr:
            return True, f"吊燈{cfg['chandelier']:.0f}ATR"
    if "ma" in cfg and held > cfg.get("grace", 0):
        line = ind[f"ma{cfg['ma']}"].at[day, sid]
        if pd.notna(line):
            if "atr_buffer" in cfg:
                atr = ind["atr"].at[day, sid]
                line = line - cfg["atr_buffer"] * (atr if pd.notna(atr) else 0)
            if c < line:
                return True, f"跌破MA{cfg['ma']}" + (f"-{cfg['atr_buffer']:.0f}ATR" if "atr_buffer" in cfg else "")
    if cfg and held >= max_hold:
        return True, f"持滿{max_hold}日上限"
    return False, ""


def buy_cost(shares, price, fee_rate):
    """買進總支出＝股票成本＋手續費（有最低收費）。"""
    gross = shares * price
    return gross + max(gross * fee_rate, MIN_FEE if gross > 0 else 0)


def sell_net(shares, price, fee_rate):
    """賣出淨收入＝股票收入－手續費－證交稅。"""
    gross = shares * price
    return gross - max(gross * fee_rate, MIN_FEE if gross > 0 else 0) - gross * TAX_RATE


def _mark(close, day, sid, last_px):
    """持倉估值用的價格：停牌（close 為 NaN）時退回最後已知收盤價，沒有則 0。

    純函數，方便測試。缺價當 0 是最容易漏掉的估值錯誤——它只在停牌那幾天出現，
    看起來像一次瞬間暴跌又瞬間復原，剛好會被最大回撤與部位縮放同時吃到。
    """
    c = close.at[day, sid] if sid in close.columns else np.nan
    if pd.notna(c):
        return float(c)
    return float(last_px.get(sid, 0.0))


def run(ind, open_, days, sig, slots, rule, max_hold, capital,
        fee_rate=FEE_RATE, max_new_per_day=None, idle_yield=None, entry_ok=None,
        regime_exit=False):
    """事件驅動模擬。回傳 (交易明細 df, 每日淨值/持倉 df)。

    成本逐筆從 cash 扣：買進加手續費（最低 20 元）、賣出扣手續費與證交稅，滑價體現在成交價。
    `max_new_per_day` 限制每日開倉數，用來檢驗「限制交易頻率」是否改善淨報酬。

    `entry_ok`（date -> bool）是大盤 regime 閘門：False 的日子不開新倉（既有部位照原
    出場規則走）。用 T 日收盤判斷、T+1 開盤成交，與訊號同一時序，無前視。動機是回撤：
    三個最佳出場規則的回撤都在 -53~-58%，而個股層的停損管不到「整個市場一起跌」。

    `idle_yield` 啟用 core-satellite：閒置現金改為持有 0050 而非空放。必須傳 **(隔夜, 盤中)
    兩段報酬**，不是單一日報酬——現金在 T+1 開盤被拿去買股，若把整段 close-to-close 報酬
    都給它，等於「賣出後仍領到賣出前的隔夜跳空、買進的現金卻沒領到自己該有的隔夜報酬」。
    拆成 `open/prev_close - 1`（開盤成交前計息）與 `close/open - 1`（收盤時計息）才對齊。
    仍簡化未計 0050 本身的進出成本，故略為樂觀。
    """
    cfg = EXIT_RULES[rule]
    if idle_yield is not None and not isinstance(idle_yield, tuple):
        raise TypeError("idle_yield 要傳 (隔夜報酬, 盤中報酬) 兩段 Series；"
                        "單一 close-to-close 序列會讓開盤成交的現金拿到錯的那一段")
    overnight_r, intraday_r = idle_yield if idle_yield is not None else (None, None)
    cash = capital
    positions, trades, equity = {}, [], []
    pending_buy, pending_sell = [], []
    fees_paid = 0.0
    # 停牌日的最後已知收盤價。缺價時把持倉市值當 0 會製造假回撤（實測單一部位可讓當日
    # 淨值掉 1/slots，且 last_equity 連帶縮小下一批部位）——台股 2013 起流動性合格股共有
    # 1,288 個停牌交易日，雖只佔曝險天數 0.127%，但剛好落在回撤谷底時會直接汙染結論。
    last_px = {}
    # 部位大小以「前一日淨值」為基準而非初始本金：用初始本金的話獲利不再投入，
    # 帳戶翻倍後新開倉仍是固定金額，曝險率會隨獲利自然下滑、大量利潤躺在現金。
    # 用前一日而非當日，是因為當日淨值要收盤才知道。
    last_equity = capital

    for i, day in enumerate(days):
        # 停泊 0050 的現金先領隔夜段（open/prev_close）——這段在開盤成交前就已實現，
        # 之後才輪到今天的買賣動用這筆現金。用當日收盤算的部分留到收盤再給。
        if overnight_r is not None:
            r = overnight_r.get(day)
            if pd.notna(r):
                cash *= (1 + r)

        # --- T+1 開盤成交（前一日收盤後決定的單子）---
        unfilled_sell = []
        for sid, reason in pending_sell:
            p = open_.at[day, sid] if sid in open_.columns else np.nan
            if sid not in positions:
                continue
            if pd.isna(p):
                # 停牌沒有開盤價 → 單子不能成交,但**必須留著**。舊版直接丟掉,已決定出場
                # 的部位會無聲地繼續持有（regime 出場更明顯：隔日 regime 恢復就永不重排）。
                unfilled_sell.append((sid, reason))
                continue
            pos = positions.pop(sid)
            exit_p = p * (1 - SLIPPAGE)
            net = sell_net(pos["shares"], exit_p, fee_rate)
            cash += net
            fees_paid += pos["shares"] * exit_p - net
            trades.append({
                "stock_id": sid, "entry_day": pos["entry_day"], "exit_day": day,
                "held": pos["held"], "reason": reason,
                "pnl": net - pos["cost"], "ret": net / pos["cost"] - 1,
            })
        pending_sell = unfilled_sell

        opened = 0
        for sid in pending_buy:
            if sid in positions or len(positions) >= slots:
                continue
            if max_new_per_day is not None and opened >= max_new_per_day:
                break
            p = open_.at[day, sid] if sid in open_.columns else np.nan
            if pd.isna(p) or p <= 0:
                continue
            target = last_equity / slots
            budget = min(target, cash)
            if budget < target * 0.5:
                continue
            entry = p * (1 + SLIPPAGE)
            shares = budget / (entry * (1 + fee_rate))  # 預留手續費，總支出不超過 budget
            cost = buy_cost(shares, entry, fee_rate)
            if cost > cash or shares <= 0:
                continue
            cash -= cost
            fees_paid += cost - shares * entry
            positions[sid] = {"shares": shares, "entry_price": entry, "cost": cost,
                              "entry_day": day, "held": 0, "peak": entry}
            opened += 1
        pending_buy = []

        # --- 當日收盤：更新持倉、判斷出場、產生明日訊號 ---
        for sid, pos in positions.items():
            pos["held"] += 1
            c = ind["close"].at[day, sid]
            if pd.notna(c):
                pos["peak"] = max(pos["peak"], c)
                last_px[sid] = c
        for sid, pos in list(positions.items()):
            hit, why = should_exit(ind, sid, day, pos, cfg, max_hold)
            if hit:
                pending_sell.append((sid, why))
        # regime 出場：只擋進場對回撤幾乎沒用（實測 -61.6% → -60.6%），因為回撤來自
        # **抱著部位穿越下跌**，不是來自新開倉。要壓回撤就得連持倉一起清。
        if regime_exit and entry_ok is not None and not entry_ok.get(day, True):
            held_ids = {s for s, _ in pending_sell}
            pending_sell += [(s, "regime出場") for s in positions if s not in held_ids]

        # 停泊現金的盤中段（close/open）在收盤才實現，故留到這裡計。
        if intraday_r is not None:
            r = intraday_r.get(day)
            if pd.notna(r):
                cash *= (1 + r)

        # 停牌（close 為 NaN）用最後已知收盤價估值，不要當成 0
        mkt = sum(pos["shares"] * _mark(ind["close"], day, sid, last_px)
                  for sid, pos in positions.items())
        last_equity = cash + mkt
        equity.append({"date": day, "equity": last_equity, "positions": len(positions),
                       "cash": cash, "fees": fees_paid})

        if i < len(days) - 1 and (entry_ok is None or entry_ok.get(day, True)):
            free = slots - len(positions) + len(pending_sell)
            if free > 0:
                pending_buy = [s for s in sig.get(day, []) if s not in positions][:free]

    last = days[-1]  # 期末強制平倉，避免未實現損益被漏計；一併扣賣出成本與滑價
    for sid, pos in positions.items():
        p = _mark(ind["close"], last, sid, last_px)
        if not p:
            continue
        net = sell_net(pos["shares"], p * (1 - SLIPPAGE), fee_rate)
        cash += net
        fees_paid += pos["shares"] * p * (1 - SLIPPAGE) - net
        trades.append({
            "stock_id": sid, "entry_day": pos["entry_day"], "exit_day": last,
            "held": pos["held"], "reason": "期末平倉",
            "pnl": net - pos["cost"], "ret": net / pos["cost"] - 1,
        })
    led = pd.DataFrame(equity).set_index("date")
    if len(positions) and len(led):
        # 期末平倉的賣出成本以前只寫進 trades、沒回寫 ledger，而 stats() 讀的是 ledger
        # → 期末淨值與 CAGR 被高估（獨立審查以合成資料量到 5,901/100 萬 ≈ 0.6%）。
        # 平倉後全部是現金，故最後一列的 equity 直接等於 cash。
        led.loc[led.index[-1], ["equity", "cash", "fees"]] = [cash, cash, fees_paid]
    return pd.DataFrame(trades), led


def _irr(cashflows, lo=-0.99, hi=10.0, tol=1e-7):
    """二分法解 IRR（年化）。cashflows: [(年數, 金額)]，投入為負、回收為正。"""
    def npv(r):
        return sum(cf / (1 + r) ** t for t, cf in cashflows)
    if npv(lo) * npv(hi) > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def dca_benchmark(price, days, daily_amount, fee_rate=FEE_RATE):
    """0050 定期定額：每個交易日投入固定金額，期末全數賣出。

    比 lump sum 更適合當本策略的基準——策略也是逐步建倉（平均曝險僅約 5 成），
    拿它跟「第一天全額進場」的 0050 比，在多頭裡對策略不公平。
    因資金逐步投入，年化用 IRR 而非 (期末/總投入)^(1/年)。
    """
    shares, invested, flows = 0.0, 0.0, []
    for d in days:
        p = price.get(d)
        if pd.isna(p) or p <= 0:
            continue
        s = daily_amount / (p * (1 + fee_rate))
        if buy_cost(s, p, fee_rate) > daily_amount:      # 最低手續費吃掉小額投入
            s = max(0.0, (daily_amount - MIN_FEE) / p)
        shares += s
        invested += daily_amount
        flows.append(((days[-1] - d).days / 365.25, -daily_amount))
    final = sell_net(shares, float(price.loc[days[-1]]), fee_rate)
    flows.append((0.0, final))
    total_years = (days[-1] - days[0]).days / 365.25
    return {"invested": invested, "final": final,
            "total_ret": final / invested - 1 if invested else float("nan"),
            "irr": _irr([(total_years - t, cf) for t, cf in flows]),
            "years": total_years}


def exposure_matched_cagr(bench_eq, ledger, years):
    """讓 0050 承受與策略相同的每日曝險，其餘為現金。

    策略平均只用約 5 成資金（其餘閒置），拿它的 CAGR 去比「第一天全額買進」的 0050
    並不對等——多頭裡閒置現金必然拖累。本基準把曝險差異抽掉，剩下的差距才是選股能力。
    曝險用前一日的（當日曝險是收盤後才知道的）。
    """
    expo = (1 - ledger["cash"] / ledger["equity"]).shift(1).fillna(0).clip(0, 1)
    r = bench_eq.pct_change().reindex(expo.index).fillna(0)
    curve = (1 + r * expo).cumprod()
    return curve.iloc[-1] ** (1 / years) - 1 if len(curve) else float("nan")


def stats(trades, ledger, capital, bench_eq, years, idle_parked=False):
    """`idle_parked`：閒置現金已停泊 0050 時，cash 欄不再代表未投入資金，
    曝險與同曝險基準會失真（實際曝險 100%），故標成 n/a，直接看年化超額。"""
    eq = ledger["equity"]
    if trades.empty:
        return {"交易筆數": 0}
    total = eq.iloc[-1] / capital - 1
    cagr = (1 + total) ** (1 / years) - 1
    daily = eq.pct_change().dropna()
    vol = daily.std() * np.sqrt(TRADING_DAYS)
    dd = (eq / eq.cummax() - 1).min()
    wins, losses = trades[trades["ret"] > 0], trades[trades["ret"] <= 0]
    bench_total = bench_eq.iloc[-1] / bench_eq.iloc[0] - 1
    bench_cagr = (1 + bench_total) ** (1 / years) - 1
    fees = ledger["fees"].iloc[-1] if "fees" in ledger else 0.0
    matched = float("nan") if idle_parked else exposure_matched_cagr(bench_eq, ledger, years)
    return {
        "年化": f"{cagr * 100:+.2f}%",
        "0050年化": f"{bench_cagr * 100:+.2f}%",
        "年化超額": f"{(cagr - bench_cagr) * 100:+.2f}%",
        "同曝險0050": "n/a" if idle_parked else f"{matched * 100:+.2f}%",
        "同曝險超額": "n/a" if idle_parked else f"{(cagr - matched) * 100:+.2f}%",
        "總報酬": f"{total * 100:+.0f}%",
        "波動": f"{vol * 100:.1f}%",
        "Sharpe": f"{cagr / vol:.2f}" if vol > 0 else "—",
        "最大回撤": f"{dd * 100:.1f}%",
        "Calmar": f"{cagr / abs(dd):.2f}" if dd < 0 else "—",
        "筆數": len(trades),
        "筆/年": f"{len(trades) / years:.0f}",
        # 用期末淨值當分母：部位隨獲利複利放大，用初始本金會讓長期獲利的策略
        # 看起來成本失控（實測 6.3 年成長 9.5 倍時，同一筆費用佔本金 66%、佔期末僅 7%）
        "手續費佔期末": f"{fees / eq.iloc[-1] * 100:.1f}%",
        "勝率": f"{len(wins) / len(trades) * 100:.1f}%",
        "賺賠比": f"{abs(wins['ret'].mean() / losses['ret'].mean()):.2f}" if len(wins) and len(losses) else "—",
        "平均持有": f"{trades['held'].mean():.0f}日",
        "曝險": "100%*" if idle_parked else f"{(1 - (ledger['cash'] / eq).mean()) * 100:.0f}%",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="screen_tw 策略回測")
    p.add_argument("--start", default="2013-01-01")
    p.add_argument("--end", default="2026-07-24")
    p.add_argument("--top", type=int, default=5, help="每日取前 N 名訊號")
    p.add_argument("--slots", type=int, default=10, help="同時持倉上限")
    p.add_argument("--exit", default="ma20", choices=sorted(EXIT_RULES))
    p.add_argument("--max-hold", type=int, default=250, help="最長持有交易日（純防呆）")
    p.add_argument("--min-turnover", type=float, default=2.0, help="日均額門檻（億）")
    p.add_argument("--capital", type=float, default=1_000_000)
    p.add_argument("--all-exits", action="store_true", help="跑全部出場規則做對照")
    p.add_argument("--by-year", action="store_true", help="輸出逐年報酬")
    p.add_argument("--periods", default=None,
                   help="逗號分隔的多個起點，輸出規則×樣本期的年化超額矩陣（穩健性檢驗）。"
                        "例：2013-01-01,2020-01-01,2024-01-01")
    p.add_argument("--factor", default="momentum", choices=sorted(FACTORS), help="進場因子")
    p.add_argument("--all-factors", action="store_true",
                   help="比較所有進場因子（固定出場規則，只換選股邏輯）")
    p.add_argument("--fee-discount", type=float, default=1.0,
                   help="券商手續費折扣（6 折填 0.6；預設 1.0 不打折）")
    p.add_argument("--max-new-per-day", type=int, default=None,
                   help="每日最多開倉數，限制交易頻率用（預設不限，受 slots 與訊號數自然約束）")
    p.add_argument("--daily-dca", type=float, default=1000.0,
                   help="0050 定期定額基準的每日投入金額（預設 1000）")
    p.add_argument("--idle-to-bench", action="store_true",
                   help="core-satellite：閒置現金停泊 0050 而非空放（同曝險超額為正時的務實解）")
    p.add_argument("--regime-ma", type=int, default=0,
                   help="大盤 regime 閘門：0050 收盤低於自身 MA(N) 的日子不開新倉（0 = 關）")
    p.add_argument("--regime-exit", action="store_true",
                   help="regime 關閉時連持倉一起清（需搭 --regime-ma）。只擋進場對回撤無效")
    p.add_argument("--null-trials", type=int, default=0,
                   help="跑 N 次隨機選股當虛無分布，判斷本因子的超額是選股力還是運氣")
    p.add_argument("--seed", type=int, default=42, help="隨機對照組的種子")
    p.add_argument("--include-tib", action="store_true",
                   help="把創新板（名稱後綴 -創）放回選股池。預設排除：一般帳戶要簽風險預告"
                        "並符合資格才能買，且全庫 25 檔只有 1 檔過得了流動性門檻——那 1 檔"
                        "（7610）在 2026 上半年 +1015%，一筆就佔 13 年總損益的 85%")
    p.add_argument("--exclude-industry", default=None,
                   help="排除 TWSE 產業代碼（逗號分隔），做報酬歸因。例：03 排除塑膠類股")
    a = p.parse_args(argv)
    if a.regime_exit and not a.regime_ma:
        # 沒有 regime 序列時 --regime-exit 是靜默 no-op，會讓人以為測過了
        p.error("--regime-exit 需要搭配 --regime-ma N（否則沒有 regime 訊號可用）")

    engine = get_engine()
    starts = [s.strip() for s in a.periods.split(",")] if a.periods else None
    # 多期比較時載入最早起點的面板；訊號只用 <= T 的資料，各期可共用同一份 precompute
    piv, inst, val, rev = load_panel(engine, min(starts) if starts else a.start, a.end)

    if not a.include_tib:
        # 創新板（TWSE Innovation Board，名稱後綴「-創」）預設不進選股池：一般帳戶要簽風險
        # 預告書並符合資格條件才能買，把它算進來的績效一般人執行不了。實務衝擊更關鍵——
        # 全庫 25 檔創新板只有 1 檔（7610 聯友金屬-創）過得了 2 億流動性門檻，而它在
        # 2026-01~07 漲了 10 倍，單一筆交易就佔 13 年總損益的 85%。用 `--include-tib` 放回。
        with engine.connect() as c:
            tib = [r[0] for r in c.execute(text(
                "select stock_id from market.stock_info where name like '%%-創'")).fetchall()]
        hit = [s for s in tib if s in piv["close"].columns]
        if hit:
            piv = {k: v.drop(columns=hit) for k, v in piv.items()}
            print(f"[池] 排除創新板 {len(hit)} 檔（--include-tib 可放回）")

    if a.exclude_industry:
        codes = {c.strip() for c in a.exclude_industry.split(",")}
        with engine.connect() as c:
            info = pd.read_sql(text("select stock_id, industry from market.stock_info"), c)
        drop = set(info[info["industry"].isin(codes)]["stock_id"])
        hit = [s for s in drop if s in piv["close"].columns]
        piv = {k: v.drop(columns=hit) for k, v in piv.items()}
        print(f"[歸因] 排除產業 {sorted(codes)}：剔除 {len(hit)} 檔\n")

    close = piv["close"]
    ind = build_indicators(close, piv["turnover"], inst, piv["pe_ratio"], piv["high"], piv["low"],
                           val=val, rev=rev)
    first = min(starts) if starts else a.start
    days = [d for d in close.index if pd.Timestamp(first) <= d <= pd.Timestamp(a.end)]
    years = len(days) / TRADING_DAYS
    etf_mask = {s: s.startswith("00") for s in close.columns}

    print(f"回測 {days[0]:%Y-%m-%d} ~ {days[-1]:%Y-%m-%d}（{len(days)} 個交易日 / {years:.1f} 年）"
          f"　池 {close.shape[1]} 檔　top{a.top}／{a.slots} 槽")

    bench = close["0050"].reindex(days).ffill()
    # regime 均線要用**截斷前**的完整序列算，否則樣本前 N 天的均線是 NaN、比較為 False，
    # 會安靜地整段不開倉（看起來像策略在那段沒訊號）。
    bench_full = close["0050"].ffill()
    entry_ok = ((bench_full > bench_full.rolling(a.regime_ma).mean()).reindex(days)
                if a.regime_ma else None)
    if entry_ok is not None:
        print(f"regime 閘門 0050 > MA{a.regime_ma}：可開倉日 "
              f"{entry_ok.sum()}/{len(entry_ok)}（{entry_ok.mean() * 100:.0f}%）")
    fee = FEE_RATE * a.fee_discount
    dca = dca_benchmark(bench, days, a.daily_dca, fee)
    # core-satellite 的停泊報酬拆成隔夜（開盤成交前實現）與盤中（收盤實現）兩段，
    # 避免「賣出的現金還領到賣出前的隔夜跳空、買進的現金卻沒領到自己的隔夜報酬」。
    bench_open = (piv["open"]["0050"].reindex(days).ffill() if a.idle_to_bench else None)
    idle = ((bench_open / bench.shift(1) - 1, bench / bench_open - 1)
            if a.idle_to_bench else None)
    lump = (bench.iloc[-1] / bench.iloc[0]) ** (1 / years) - 1
    print(f"成本 手續費{fee * 100:.4f}%/邊(最低{MIN_FEE}元) 證交稅{TAX_RATE * 100:.1f}% "
          f"滑價{SLIPPAGE * 100:.2f}%/邊"
          + (f"　每日最多開倉 {a.max_new_per_day}" if a.max_new_per_day else ""))
    print(f"基準 0050 一次買進年化 {lump * 100:+.2f}%　|　"
          f"每日定額{a.daily_dca:,.0f}元 IRR {dca['irr'] * 100:+.2f}% "
          f"(投入{dca['invested']:,.0f} 期末{dca['final']:,.0f} 總報酬{dca['total_ret'] * 100:+.1f}%)\n")

    if a.all_factors:
        # 固定出場規則，只換選股邏輯——出場已證實改善有限，瓶頸在進場因子。
        bench_cagr = (bench.iloc[-1] / bench.iloc[0]) ** (1 / years) - 1
        print(f"固定出場規則 {a.exit}　0050 年化 {bench_cagr * 100:+.2f}%\n")
        rows = []
        for fac in sorted(FACTORS):
            fsig = precompute_signals(ind, days, a.min_turnover * 1e8, a.top, etf_mask, fac)
            n = sum(len(v) for v in fsig.values())
            tr, led = run(ind, piv["open"], days, fsig, a.slots, a.exit, a.max_hold, a.capital,
                          fee_rate=fee, max_new_per_day=a.max_new_per_day,
                          idle_yield=idle, entry_ok=entry_ok, regime_exit=a.regime_exit)
            st = stats(tr, led, a.capital, bench, years, idle_parked=a.idle_to_bench)
            rows.append((fac, n / max(len(days), 1), st))
        keys = [k for k in rows[0][2]]
        print(f"{'進場因子':<16}{'訊號/日':>9}" + "".join(f"{k:>10}" for k in keys))
        for fac, per_day, st in sorted(rows, key=lambda x: -float(x[2].get("年化", "0%").rstrip("%"))):
            print(f"{fac:<18}{per_day:>9.1f}" + "".join(f"{str(v):>10}" for v in st.values()))
        return 0

    if a.null_trials:
        # 「超額 +15% 是選股力還是運氣」只有虛無分布能回答：同一出場規則、同樣槽數下
        # 隨機選股跑 N 次。真因子若落在隨機分布裡面，那不是 alpha。
        #
        # **對照組用本因子自己的 filter，不是全池隨機**：`monthly_revenue` 只覆蓋 1,152/2,679
        # 檔（幾乎全是上市；流動性合格股裡占 61%），拿全池隨機當對照的話，「revenue 贏隨機」
        # 有一部分只是「上市大型股贏上櫃小型股」的宇宙差異，不是排序能力。同宇宙隨機才
        # 隔離出排序本身的貢獻。全池隨機仍可用 `--all-factors` 的 `random` 因子看。
        FACTORS["_null"] = {
            "filter": FACTORS[a.factor]["filter"],
            "score": lambda r, f: pd.Series(np.random.rand(len(f)), index=f.index),
        }
        key = "年化超額" if a.idle_to_bench else "同曝險超額"

        def _excess(fac):
            fs = precompute_signals(ind, days, a.min_turnover * 1e8, a.top, etf_mask, fac)
            tr, led = run(ind, piv["open"], days, fs, a.slots, a.exit, a.max_hold, a.capital,
                          fee_rate=fee, max_new_per_day=a.max_new_per_day,
                          idle_yield=idle, entry_ok=entry_ok, regime_exit=a.regime_exit)
            st = stats(tr, led, a.capital, bench, years, idle_parked=a.idle_to_bench)
            return float(str(st.get(key, "nan")).rstrip("%"))

        real = _excess(a.factor)
        if not np.isfinite(real):
            print(f"**因子 {a.factor} 在此設定下沒有有效績效（可能零成交），無法做檢驗")
            return 1
        np.random.seed(a.seed)
        raw = np.array([_excess("_null") for _ in range(a.null_trials)])
        # **NaN 必須剔除而不是留在分母**：某次隨機試驗零成交時 `stats()` 不回超額欄，
        # `_excess` 得到 NaN；`NaN >= real` 算 False 卻仍佔一個分母，會壓低經驗 p，
        # 同時讓 mean/sd/z 全變 NaN。有效試驗數要跟著回報，否則 p 的下限被高估。
        null = raw[np.isfinite(raw)]
        n_ok = len(null)
        if n_ok < 2:
            print(f"**有效隨機試驗只有 {n_ok}/{a.null_trials} 次，樣本不足無法做檢驗")
            return 1
        beat = int((null >= real).sum())
        sd = null.std(ddof=1)
        print(f"=== 虛無分布檢驗（{key}／出場 {a.exit}／{a.slots} 槽／"
              f"{n_ok} 次有效（共 {a.null_trials} 次））===")
        print(f"  對照組 = {a.factor} 的同一組 filter + 隨機排序（隔離「排序能力」與「宇宙差異」）")
        print(f"  {a.factor:<16}{real:+.2f}%")
        print(f"  同宇宙隨機選股  平均 {null.mean():+.2f}%　標準差 {sd:.2f}%　"
              f"範圍 {null.min():+.2f}% ~ {null.max():+.2f}%")
        z = (real - null.mean()) / sd if sd > 0 else float("nan")
        print(f"  隨機贏過本因子 {beat}/{n_ok} 次　經驗 p = "
              f"{(beat + 1) / (n_ok + 1):.3f}　z = {z:+.2f}")
        # 經驗 p 的下限是 1/(N+1)：10 次試驗最小只能到 0.091,要更小的 p 得加試驗數。
        print(f"\n  p 大於 0.1 就別當成選股能力——同一組門檻下隨機挑也做得到。"
              f"（本次 p 下限 = 1/(N+1) = {1 / (n_ok + 1):.3f}，看 z 分數更有解析度）")
        if n_ok < a.null_trials:
            print(f"  注意：{a.null_trials - n_ok} 次試驗無有效績效已剔除，未計入分母。")
        return 0

    sig = precompute_signals(ind, days, a.min_turnover * 1e8, a.top, etf_mask, a.factor)
    n_sig = sum(len(v) for v in sig.values())
    print(f"進場因子 {a.factor}　訊號共 {n_sig:,} 個（平均每日 {n_sig / len(days):.1f} 個）\n")

    rules = sorted(EXIT_RULES) if a.all_exits else [a.exit]

    if starts:
        # 穩健性檢驗：同一份訊號、同一組規則，只換樣本期。單期的第一名可能是運氣，
        # 跨期都在前段才值得相信。
        grid, ranks = {}, {}
        for s in starts:
            dsub = [d for d in days if d >= pd.Timestamp(s)]
            yrs = len(dsub) / TRADING_DAYS
            bsub = close["0050"].reindex(dsub).ffill()
            col = {}
            for rule in rules:
                tr, led = run(ind, piv["open"], dsub, sig, a.slots, rule, a.max_hold, a.capital,
                              fee_rate=fee, max_new_per_day=a.max_new_per_day,
                              idle_yield=idle, entry_ok=entry_ok,
                             regime_exit=a.regime_exit)
                st = stats(tr, led, a.capital, bsub, yrs, idle_parked=a.idle_to_bench)
                col[rule] = float(st.get("年化超額", "0%").rstrip("%")) if st.get("年化超額") else float("nan")
            grid[s] = col
            order_s = sorted(col, key=lambda r: -col[r])
            ranks[s] = {r: i + 1 for i, r in enumerate(order_s)}
            print(f"[{s}] {len(dsub)} 交易日 / {yrs:.1f} 年　0050 年化 "
                  f"{((bsub.iloc[-1] / bsub.iloc[0]) ** (1 / yrs) - 1) * 100:+.2f}%")

        avg_rank = {r: sum(ranks[s][r] for s in starts) / len(starts) for r in rules}
        print(f"\n=== 年化超額 (%)　規則 × 樣本期　共 {len(rules)} 規則 ===")
        print(f"{'出場規則':<16}" + "".join(f"{s[:7]:>12}" for s in starts) + f"{'平均排名':>10}")
        for rule in sorted(rules, key=lambda r: avg_rank[r]):
            row = "".join(f"{grid[s][rule]:>+12.2f}" for s in starts)
            print(f"{rule:<18}{row}{avg_rank[rule]:>10.1f}")
        print("\n平均排名越小越穩健；跨期都在前段的規則才值得相信，單期第一名可能只是運氣。")
        return 0

    results = {}
    for rule in rules:
        trades, ledger = run(ind, piv["open"], days, sig, a.slots, rule, a.max_hold, a.capital,
                             fee_rate=fee, max_new_per_day=a.max_new_per_day,
                             idle_yield=idle, entry_ok=entry_ok,
                             regime_exit=a.regime_exit)
        results[rule] = (trades, ledger, stats(trades, ledger, a.capital, bench, years, idle_parked=a.idle_to_bench))

    keys = list(results.values())[0][2]
    print(f"{'出場規則':<14}" + "".join(f"{k:>10}" for k in keys))
    order = sorted(results, key=lambda r: -float(results[r][2]["年化"].rstrip("%")))
    for rule in order:
        s = results[rule][2]
        print(f"{rule:<16}" + "".join(f"{str(v):>10}" for v in s.values()))

    trades, ledger, _ = results[order[0] if a.all_exits else rules[0]]
    best = order[0] if a.all_exits else rules[0]
    if not trades.empty:
        print(f"\n=== {best} 出場原因分布 ===")
        g = trades.groupby("reason").agg(筆數=("ret", "size"), 平均報酬=("ret", "mean"), 總損益=("pnl", "sum"))
        g["平均報酬"] = (g["平均報酬"] * 100).round(2)
        g["總損益"] = g["總損益"].round(0)
        print(g.sort_values("總損益", ascending=False).to_string())
        tot = trades["pnl"].sum()
        top1, top10 = trades["pnl"].max(), trades.nlargest(10, "pnl")["pnl"].sum()
        if tot <= 0:
            # 總損益 <= 0 時「佔比」沒有意義（負分母會印出反向的百分比、零會除零）
            print(f"\n報酬集中度：總損益為 {tot:,.0f}（<= 0），佔比不適用；"
                  f"單筆最大 {top1:,.0f}、前 10 筆合計 {top10:,.0f}（共 {len(trades)} 筆）")
        elif a.idle_to_bench:
            # idle 模式下分母不含 0050 停泊收益，稱不上「組合總損益佔比」
            print(f"\n報酬集中度（僅個股交易，不含 0050 停泊收益）：單筆最大佔 "
                  f"{top1 / tot * 100:.0f}%、前 10 筆佔 {top10 / tot * 100:.0f}%"
                  f"（共 {len(trades)} 筆）")
        else:
            # 集中度是「這是策略還是彩票」的直接檢查：單筆佔比到兩三成就別當可重複的能力
            print(f"\n報酬集中度：**單筆最大佔 {top1 / tot * 100:.0f}%**、前 10 筆佔 "
                  f"{top10 / tot * 100:.0f}% 的總損益（共 {len(trades)} 筆）")
        cols = ["stock_id", "entry_day", "exit_day", "held", "ret", "pnl", "reason"]
        show = trades.assign(ret=(trades["ret"] * 100).round(1), pnl=trades["pnl"].round(0))
        print(f"\n=== 最賺 8 筆 ===\n{show.nlargest(8, 'pnl')[cols].to_string(index=False)}")
        print(f"\n=== 最賠 5 筆 ===\n{show.nsmallest(5, 'pnl')[cols].to_string(index=False)}")
        if a.by_year:
            print(f"\n=== {best} 逐年報酬 vs 0050 ===")
            eq, ye = ledger["equity"], ledger["equity"].resample("YE").last()
            yb = bench.resample("YE").last()
            pe_, pb_ = ye.shift(1).fillna(a.capital), yb.shift(1).fillna(bench.iloc[0])
            for (d, v), sv, bv, bp in zip(ye.items(), pe_.values, yb.values, pb_.values):
                sr, br = v / sv - 1, bv / bp - 1
                print(f"  {d:%Y}: 策略 {sr * 100:+7.2f}%   0050 {br * 100:+7.2f}%   超額 {(sr - br) * 100:+7.2f}%")
            _ = eq
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
