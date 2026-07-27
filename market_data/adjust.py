"""重建 ``market.price_adjustment``：把三類公司行動收斂成單一前復權因子表。

``price`` 存的是未還原價。要算報酬、均線、乖離之前一定要套這張表，否則除息/分割的
跳空會被當成真實漲跌——0050 的 1:4 分割就曾讓回測的 0050 基準在 2025 年顯示 -65.79%。

三個來源，官方優先：

| kind      | source          | 覆蓋              | 精度 |
| --------- | --------------- | ----------------- | ---- |
| dividend  | twse_twt49u     | 上市除權息        | 官方公告值 |
| dividend  | tpex_exdailyq   | 上櫃除權息        | 官方公告值 |
| reduction | twse_twtauu     | 上市減資          | 官方公告值 |
| split     | verified_manual | 人工核對的 ETF    | 比對公告後寫死 |
| split     | inferred_price  | 普通股分割(≈1/N)  | 吸附到精確 1/N |
| inferred  | inferred_price  | 上櫃減資等剩餘事件 | 回推,誤差 ≤10% |

推導的理論依據：台股普通股有 ±10% 漲跌幅限制，所以單日 >15% 跳空必為公司行動。
**這個前提只對普通股成立**——ETF／ETN／TDR 依官方規則不受漲跌幅限制（部分海外 ETF、
槓反產品、第二上市外國證券），對它們推導必然製造假事件，故一律排除、只收官方值或
``VERIFIED_ACTIONS`` 白名單。

不推導的情況（會誤判成公司行動的真實波動）：
  - 非普通股（見 ``is_common_stock``）
  - 上市初期前 6 根 K（台股新上市首 5 日無漲跌幅限制）
  - 距前一筆交易 ≥14 天（長期停牌後恢復買賣，跳空反映的是停牌期間的資訊）；
    但比例吸附到精確 1/N 或 N 倍時例外收錄——減資停牌本來就是 2~3 週

**已知限制**：
  - 剩餘的推導值主要是上櫃減資（TWTAUU 僅上市，無公開的上櫃減資端點），以開盤價回推、
    無法證明精確；正式用途應逐筆與官方公告對表。
  - 同一檔同一天只能存一筆事件（PK 為 ``(stock_id, date)``）。三個官方來源實測**零交集**
    （上市除權息 14,908 × 上市減資 347 × 上櫃除權息 10,892，兩兩交集皆 0 筆），故此限制
    目前不會造成漏記；未來新增來源時要重驗。

**預設從 2013 起**：`price` 表的 2010 上半年混有約 1,000 檔權證（5 位數代號，每日檔數
2,200+ 對比 2011 之後的 1,380）。權證無漲跌幅限制且波動極大，納入推導會產生兩萬筆以上
的假事件。要涵蓋更早期得先把權證從 price 表清掉。

用法：
    uv run --env-file .env python -m market_data.cli adjust
    uv run --env-file .env python -m market_data.cli adjust --start 2013-01-01
"""

import datetime

import numpy as np
import pandas as pd
from sqlalchemy import text

from market_data import models, sources
from market_data.db import get_engine
from market_data.writer import upsert

# 台股漲跌幅限制在 2015-06-01 由 ±7% 放寬為 ±10%；門檻依當時制度取 1.1 倍緩衝。
PRICE_LIMIT_CHANGE = "2015-06-01"
SPLIT_RATIOS = (2, 3, 4, 5, 6, 7, 8, 10, 20, 25, 50, 100)
MIN_BARS_BEFORE = 6     # 上市初期不推導（前 5 日無漲跌幅限制）
STALE_GAP_DAYS = 14     # 距前一筆交易超過此天數視為停牌後恢復，不推導
MAX_SPLIT_GAP_DAYS = 60  # 精確比例可越過 STALE_GAP_DAYS，但停牌超過此天數一律不推導

# 只有「受 ±10% 漲跌幅限制的普通股」能用價格推導。ETF／ETN／TDR 等依官方規則
# 不受漲跌幅限制（部分海外 ETF、槓反產品、第二上市外國證券），推導必然誤判——
# 踩過：00887 在 2024-10-08、10-14 的真實 -48%／-51% 崩跌（海外休市、溢價逾 200% 的
# 價格異常）被判成兩次 1:2 分割，把跌幅改寫成 +3%／-2%，還讓之前的歷史價全乘 0.25。
# 這批商品只接受官方值或下方人工核對清單。
def is_common_stock(stock_id: str) -> bool:
    """四位純數字、且非 ETF/TDR 前綴，才視為受漲跌幅限制的普通股。

    踩雷：**TDR 也有四位數代號**（9103 美德醫療-DR、9105 泰金寶-DR、9110 越南控-DR、
    9136 巨騰-DR），光靠長度擋不掉；而 9802、9904 寶成、9921 巨大這些 9 開頭的
    卻是正常普通股，所以只能用 `91` 前綴區分。帶字母的特別股（9941A）由 isdigit 擋掉。
    """
    if len(stock_id) != 4 or not stock_id.isdigit():
        return False            # ETN(020xxx)、6 位 TDR(910322)、權證(5 位) 一併排除
    return not stock_id.startswith(("00", "91"))


# 人工核對過的非普通股公司行動（factor = 恢復後價 / 前價）。
# 自動推導對這類商品不可靠（見 00887），故 ETF 的真分割一律走白名單。
# 判準：價格比與理論比例的相對誤差需 <1%（真分割 0.005~0.9%，00887 的假事件是 3%）。
VERIFIED_ACTIONS = {
    ("0050", "2025-06-18"): 1 / 4,    # 188.65 → 47.57，誤差 0.88%
    ("00631L", "2026-03-31"): 1 / 23,  # 443.15 → 19.26，誤差 0.005%
    ("00685L", "2026-07-07"): 1 / 25,  # 306.00 → 12.23，誤差 0.08%
    ("00632R", "2024-12-11"): 7.0,     # 反分割 7 合 1；3.28 → 23.12，誤差 0.7%
}


# 相對誤差上限。以開盤價為基準時，實測真分割的誤差是 0~2.0%（6763 為 0.0%、5314 為
# 0.7%、4763 為 1.9%、8422 為 2.0%），而 00887 那筆被誤判的真崩跌是 3.0%。
# 舊版 0.15/N 在 1/2 時等於 ±7.5%，寬到足以放行假事件。2.5% 剛好分開兩者。
SPLIT_TOLERANCE = 0.025


def _snap_to_split(factor):
    """因子接近 1/N（分割）或 N（反分割）就吸附到精確值，回傳 (吸附後因子, 是否為分割)。

    用**相對誤差**而非絕對值，且 factor 須以開盤價計算——收盤價會同時混入當日盤中
    漲跌，讓比例失真（6763 用開盤價是精確 1/10，用收盤價變成 1/10.54）。
    """
    for n in SPLIT_RATIOS:
        for target in (1 / n, float(n)):     # 分割與反分割（如 00632R 的 7 合 1）
            if abs(factor - target) / target < SPLIT_TOLERANCE:
                return target, True
    return factor, False


def official_rows(conn):
    """已有官方公告值的事件：ex_dividend(除權息) + price_adjustment 既存的 twtauu。"""
    df = pd.read_sql(text(
        "select stock_id, date, close_before, reference_price from market.ex_dividend "
        "where close_before > 0 and reference_price > 0"
    ), conn, parse_dates=["date"])
    df["factor"] = df["reference_price"].astype(float) / df["close_before"].astype(float)
    df["kind"] = "dividend"
    df["source"] = "twse_twt49u"
    return df


def _fetch_by_year(crawl, start, end, chunk_days=365, delay=1.0):
    """逐年打區間端點並串起來。切年是因為單次跨十幾年的回應會被截斷或超時；
    ``delay`` 是逐年之間的間隔，官方站對密集請求會限流（TWSE 還會靜默回 None）。

    **任一段失敗就 raise，不是跳過。** 舊版只在「所有段都失敗」時才回空，於是
    「2018 那段回 None、其他年成功」的結果仍然非空，`rebuild()` 會照樣先刪整段再寫入
    缺 2018 的資料——缺一年的官方除權息足以讓那年之後的所有報酬計算全錯，而且完全無聲。
    """
    import time

    out = []
    cur = start
    while cur <= end:
        nxt = min(cur + datetime.timedelta(days=chunk_days), end)
        df = crawl(cur, nxt)
        if df is None:
            raise RuntimeError(
                f"官方來源 {getattr(crawl, '__name__', crawl)} 在 {cur} ~ {nxt} 這段抓取失敗"
                f"（網路或端點改版）。已中止，未更動 DB——部分年度的資料寫進去會靜默污染"
                f"整段歷史。稍後重試或改用較短的 --start。")
        if len(df):
            out.append(df)
        cur = nxt + datetime.timedelta(days=1)
        if delay and cur <= end:
            time.sleep(delay)
    if not out:
        return pd.DataFrame(columns=["stock_id", "date", "close_before", "reference_price"])
    return pd.concat(out, ignore_index=True).drop_duplicates(subset=["stock_id", "date"])


def fetch_reductions(start, end, chunk_days=365):
    """抓 TWTAUU 減資公告（上市）。"""
    df = _fetch_by_year(sources.crawl_reduction, start, end, chunk_days)
    if not len(df):
        return df
    df["factor"] = df["reference_price"] / df["close_before"]
    df["kind"] = "reduction"
    df["source"] = "twse_twtauu"
    return df


def fetch_tpex_dividends(start, end, chunk_days=365):
    """抓上櫃除權除息計算結果表（官方參考價）。

    這批取代原本 1,183 筆價格推導值裡的上櫃除權息部分——推導以開盤價回推，誤差 ≤10%
    且無法證明；有官方值就沒有理由再猜（端點怎麼找到的見 ``sources.crawl_tpex_ex_dividend``）。
    """
    df = _fetch_by_year(sources.crawl_tpex_ex_dividend, start, end, chunk_days)
    if not len(df):
        return df
    df["factor"] = df["reference_price"] / df["close_before"]
    df["kind"] = "dividend"
    df["source"] = "tpex_exdailyq"
    return df


def infer_rows(conn, known, start):
    """從價格跳空回推未被官方資料解釋的公司行動。``known`` 是已解釋的 (stock_id, date)。

    **用開盤價當參考價的代理**，不是收盤價。台股除權息／恢復買賣當日的開盤競價基準
    就是官方參考價，開盤價偏離它的幅度遠小於收盤價。用收盤價會讓 factor 定義成
    `close/prev_close`，數學上強制把事件日報酬變成 0，等於把公司行動與當日市場報酬
    一起抹掉（獨立審查指出，每筆可錯 ±10%）。改用開盤價後，事件日的盤中漲跌得以保留。
    """
    # 多讀 60 天再往前算 seq/gap：查詢先截在 `start` 的話，任何**既有**股票在起點後的
    # 前 6 根 K 都會被 MIN_BARS_BEFORE 當成「新上市」排除，那幾天的公司行動就永久漏記。
    # 事件本身仍只收 >= start（rebuild 只刪這段，寫回更早的列會與既有資料不一致）。
    lookback = (pd.Timestamp(start) - pd.Timedelta(days=60)).date()
    px = pd.read_sql(text(
        "select stock_id, date, open, close from market.price "
        "where date >= :s and close > 0 and open > 0"
    ), conn, params={"s": lookback}, parse_dates=["date"])
    for col in ("open", "close"):
        px[col] = px[col].astype(float)
    px = px.sort_values(["stock_id", "date"])
    g = px.groupby("stock_id")
    px["prev"] = g["close"].shift(1)
    px["seq"] = g.cumcount()
    px["gap"] = g["date"].diff().dt.days
    px = px[px["prev"].notna()]
    px["factor"] = px["open"] / px["prev"]

    # 門檻跟著當時實際的漲跌幅限制走：2015-06-01 前是 ±7%，之後才放寬為 ±10%。
    # 固定用 15% 會漏掉舊制下 7~15% 的公司行動（獨立審查指出）。取 1.1 倍緩衝。
    limit = np.where(px["date"] < pd.Timestamp(PRICE_LIMIT_CHANGE), 0.07, 0.10) * 1.1
    jump = px[(px["factor"] - 1).abs() > limit].copy()
    explained = pd.Series([(s, d) in known for s, d in zip(jump["stock_id"], jump["date"])],
                          index=jump.index)
    jump = jump[~explained & (jump["seq"] >= MIN_BARS_BEFORE)]

    # 只推導普通股。非普通股（ETF/ETN/TDR）不受漲跌幅限制，價格推導必然製造假事件。
    jump = jump[jump["stock_id"].map(is_common_stock)].copy()
    snapped = jump["factor"].map(_snap_to_split)
    jump["factor"] = snapped.map(lambda s: s[0])
    jump["is_split"] = snapped.map(lambda s: s[1])
    # 停牌後復牌的跳空多半反映停牌期間累積的資訊，不是公司行動 → 不推導。
    # **精確 1/N（或 N 倍）比例是例外**：減資的停止買賣窗口本來就是 2~3 週，用 gap 一刀切
    # 會把最常見的上櫃減資整批漏掉——實測 gap>=14 被排除的 152 筆裡有 13 筆吸附到精確比例，
    # 其中 11 筆的 gap 落在 14~28 天（2719、3339、4303、5205、6228… 全是減資後復牌的 2~4 倍跳升）。
    # **但例外有上限**：停牌越久，「復牌價恰好落在 1/N 附近」越可能只是停牌期間的真實
    # 重估碰巧撞上比例，而推導錯一筆就把該檔之前的全部歷史價乘錯。實測 gap>=14 的 13 筆
    # 精確比例事件裡，11 筆的 gap 在 14~28 天（減資窗口），另外 2 筆是 6222（195 天）與
    # 6131（328 天）——那兩筆需人工對官方公告，確認後放進 VERIFIED_ACTIONS，不走推導。
    jump = jump[(jump["is_split"] & (jump["gap"] < MAX_SPLIT_GAP_DAYS))
                | (jump["gap"] < STALE_GAP_DAYS)]
    jump = jump[jump["date"] >= pd.Timestamp(start)]   # 前置的 60 天只用來算 seq/gap
    jump["kind"] = jump["is_split"].map({True: "split", False: "inferred"})
    jump["source"] = "inferred_price"
    jump["close_before"] = jump["prev"]
    jump["reference_price"] = jump["open"]
    return jump[["stock_id", "date", "factor", "kind", "source", "close_before", "reference_price"]]


_NETWORK_SOURCES = ("tpex_exdailyq", "twse_twtauu")


def existing_official_rows(conn, start, sources_=_NETWORK_SOURCES):
    """讀回 DB 裡已有的網路來源官方列（離線重算時沿用，不重抓也不清掉）。

    `rebuild()` 會先 `delete where date >= start`。若離線模式只是「不抓」而沒有把既有
    官方列讀回來，`--no-reductions` 實際上等於刪掉 10,879 筆上櫃除權息與 347 筆減資——
    而它的說明寫的是「跳過抓取」，使用者不會預期資料被清空。
    """
    return pd.read_sql(text(
        "select stock_id, date, factor, kind, source, close_before, reference_price "
        "from market.price_adjustment where date >= :s and source = any(:src)"),
        conn, params={"s": start, "src": list(sources_)}, parse_dates=["date"])


def rebuild(engine=None, start="2013-01-01", with_reductions=True):
    """重建整張 price_adjustment。回傳各來源筆數。

    ``with_reductions``（CLI 的 ``--no-reductions`` 反向）關掉兩個需要網路的官方來源
    （TWTAUU 減資、TPEx 上櫃除權息），改為**沿用 DB 裡既有的那些列**，只離線重算價格
    推導部分。它不是破壞性操作——官方列會被讀回來一起寫入。
    """
    eng = engine or get_engine()
    start_d = datetime.date.fromisoformat(start) if isinstance(start, str) else start
    cols = ["stock_id", "date", "factor", "kind", "source", "close_before", "reference_price"]

    with eng.connect() as conn:
        off = official_rows(conn)

    # 順序即優先序（下面 drop_duplicates keep="first"）：
    # 上市除權息 > 上櫃除權息 > 減資 > 人工核對 > 價格推導
    parts = [off]
    if with_reductions:
        today = datetime.date.today()
        tpex = fetch_tpex_dividends(start_d, today)
        if not len(tpex):
            raise RuntimeError(
                "TPEx 上櫃除權息來源抓取失敗；已中止，未更動 DB。"
                "確定要跳過官方來源請加 --no-reductions（會沿用 DB 既有官方列）。")
        parts.append(tpex)
        red = fetch_reductions(start_d, today)
        if not len(red):
            # rebuild 會先刪除既有列，來源抓失敗還照寫等於把官方減資資料清空。
            # 網路不通時寧可整批不發布（要離線重算推導部分請用 --no-reductions）。
            raise RuntimeError(
                "TWTAUU 減資來源抓取失敗（可能被 TWSE 暫時封鎖）；已中止，未更動 DB。"
                "確定要跳過減資請加 --no-reductions（會沿用 DB 既有官方列）。")
        parts.append(red)
    else:
        with eng.connect() as conn:
            keep = existing_official_rows(conn, start_d)
        print(f"[adjust] --no-reductions：沿用 DB 既有官方列 {len(keep):,} 筆（不重抓、不清空）")
        if len(keep):
            parts.append(keep)

    verified = pd.DataFrame([
        {"stock_id": sid, "date": pd.Timestamp(d), "factor": f,
         "kind": "split", "source": "verified_manual",
         "close_before": None, "reference_price": None}
        for (sid, d), f in VERIFIED_ACTIONS.items()
    ])
    if len(verified):
        parts.append(verified)

    merged = pd.concat([p.reindex(columns=cols) for p in parts], ignore_index=True)
    merged = merged.drop_duplicates(subset=["stock_id", "date"], keep="first")
    known = set(zip(merged["stock_id"], merged["date"]))

    with eng.connect() as conn:
        inf = infer_rows(conn, known, start_d)

    final = pd.concat([merged, inf.reindex(columns=cols)], ignore_index=True)
    final = final.drop_duplicates(subset=["stock_id", "date"], keep="first")
    # 因子必須是有限正數：0/NaN 會讓整條累乘塌掉，inf 會炸掉整段歷史價
    f = pd.to_numeric(final["factor"], errors="coerce")
    final = final[np.isfinite(f) & (f > 0)]
    final["date"] = pd.to_datetime(final["date"]).dt.date

    recs = final.to_dict("records")
    # Postgres 單次查詢上限 65535 個參數；7 欄 × 4 萬列會爆，切批寫入
    batch = 5000
    n = 0
    with eng.begin() as conn:
        # 真正的「重建」：先刪掉本次涵蓋範圍的舊列，否則被新邏輯否決的錯事件
        # （如 00887 的假分割）會永久殘留，改了判斷也清不掉。
        conn.execute(text("delete from market.price_adjustment where date >= :s"),
                     {"s": start_d})
        for i in range(0, len(recs), batch):
            n += upsert(conn, models.PriceAdjustment.__table__,
                        recs[i:i + batch], ["stock_id", "date"])
    return {"written": n, **final.groupby("source").size().to_dict(),
            "by_kind": final.groupby("kind").size().to_dict()}


def factors_to_panel(adj, index, columns):
    """把 (stock_id, date, factor) 長格式攤成可直接乘上價格的前復權面板。

    adj[t] = Π factor[s] for s > t —— 事件日之前的價格下修，最新價維持原值。
    純函數（不碰 DB），見 tests/test_price_adjustment.py。
    """
    fac = pd.DataFrame(1.0, index=index, columns=columns)
    adj = adj[adj["stock_id"].isin(set(columns))]
    for _, r in adj.iterrows():
        d = pd.Timestamp(r["date"])
        if d in fac.index:  # 同日多事件相乘；事件日不在交易日曆上時跳過
            fac.at[d, r["stock_id"]] *= float(r["factor"])
    return fac[::-1].cumprod()[::-1] / fac


def load_factors(engine, index, columns):
    """讀 price_adjustment 並回傳前復權面板（index=date, columns=stock_id）。"""
    with engine.connect() as conn:
        adj = pd.read_sql(text(
            "select stock_id, date, factor from market.price_adjustment"
        ), conn, parse_dates=["date"])
    return factors_to_panel(adj, index, columns)
