#!/usr/bin/env python3
"""回驗 `tw-swing-research` 的判斷：AI 那一層到底有沒有加值。

量化層的候選池已經是正期望值（974 個事件、均值 +9.93%），所以「進場的那些賺錢」證明不了
任何事——**全收也會賺**。這支腳本因此不看命中率，看四個量：

    E[R|enter] − E[R|全收]   選出來的比全收好多少（<0 就是這層在扣分）
    E[R|pass]               放棄掉的後來漲了多少（機會成本）
    Brier(conf) vs Brier(基準率)   `confidence` 有沒有比「一律報 20.2%」更準
    可成交口徑               同樣 slots 個空位下「全收 vs 只收 enter」兩本帳

最後一項不可省：事件均值可以被同日同題材的一堆訊號撐高，但真實帳戶只拿得到 slots 檔。
前三項的結論一律要求 bootstrap 區間不跨零**且**已到期樣本過門檻，否則標為 inconclusive——
差值本身永遠不等於零，「>0 就有加值」是空話。

報酬定義與 `measure_signal_forward.py` 一致：前復權價、次一交易日開盤買進、第 60 個交易日
收盤賣出，並計入雙邊滑價、手續費及賣出證交稅。進場日取「訊號日與 `decided_at` 兩者較晚者」的次一
交易日——只看訊號日會讓「週五訊號、週一晚間才研究完」的判斷用到週一白天的開盤價。

用法：
    uv run --env-file .env python scripts/verify_swing_decisions.py
    uv run --env-file .env python scripts/verify_swing_decisions.py --log path/to.jsonl
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from market_data.adjust import load_factors  # noqa: E402
from market_data.closures import adhoc_closed_dates, tw_closed_reason  # noqa: E402
from market_data.db import get_engine  # noqa: E402
from measure_signal_forward import (  # noqa: E402
    DEFAULT_POSITION_NOTIONAL, paired_block_bootstrap,
)
from tw_trade_costs import round_trip_return  # noqa: E402

LOG = Path("journal/swing-decisions.jsonl")   # 進版控：見 journal/README.md
# Version-controlled closure list (the data/ one is gitignored and XTAI misses ad-hoc closures).
CLOSED_DATES = Path(__file__).resolve().parent.parent / "journal" / "closed-dates.txt"
BASE_RATE = 0.202        # 現行成本口徑 P(第 60 日收盤淨報酬 ≥ +30%)
MIN_MATURED = 20         # 低於這個數量的結論一律標為雜訊


def read_log(path, drop_closed=True):
    """讀日誌；訊號日是休市日（臨時休市清單或非交易日）的列不計入回驗。

    journal 是 append-only，休市日照跑的判讀不能改，所以在讀取端排除；筆數記在 attrs。
    """
    rows = []
    for ln, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{ln} 不是合法 JSON（一行一個決策）: {exc}")
    df = pd.DataFrame(rows)
    df.attrs["closed_excluded"] = 0
    if drop_closed and len(df) and "date" in df.columns:
        # fetch=lambda: None: only the adhoc-closure list + XTAI calendar, never the network.
        tracked = adhoc_closed_dates(CLOSED_DATES)
        closed = {d for d in df["date"].dropna().unique()
                  if datetime.date.fromisoformat(str(d)) in tracked
                  or tw_closed_reason(datetime.date.fromisoformat(str(d)), fetch=lambda: None)}
        df = df[~df["date"].isin(closed)].reset_index(drop=True)
        df.attrs["closed_excluded"] = len(rows) - len(df)
    return df


def window(cal, d, horizon, decided_at=None):
    """(訊號日, 判斷時點) → (進場日, 出場日, 還差幾個交易日)。未到期時前兩者為 None。

    進場日是**晚於「訊號日與判斷時點兩者較晚者」的第一個交易日**。只用訊號日是錯的：
    週五的候選若到週一晚間才研究完，用週一開盤成交等於拿週一白天還不存在的判斷去下單
    （`decided_at` 就是為了讓這件事可稽核才要求填的）。判斷時點只取到日，所以盤前做的
    判斷會被保守地延後一天。

    持有長度固定 `horizon` 個交易日（進場日算第 1 天），與 `measure_signal_forward` 的
    「T+1 開盤 → T+h 收盤」逐格一致。
    """
    base = pd.Timestamp(d)
    if decided_at is not None and not (isinstance(decided_at, float) and np.isnan(decided_at)):
        da = pd.Timestamp(decided_at)
        if da.tzinfo is not None:
            da = da.tz_convert("Asia/Taipei").tz_localize(None)
        base = max(base, da.normalize())
    i = int(cal.searchsorted(base, side="right")) - 1
    if i < 0:
        return None, None, np.nan
    if i + horizon >= len(cal):
        return None, None, i + horizon - (len(cal) - 1)
    return cal[i + 1], cal[i + horizon], 0


def fill_ok(entry_px, entry_range):
    """開盤價有沒有落在建議進場區間內（沒填區間就一律算成交）。

    開盤跳空穿過區間**上界** = 這筆根本沒成交，算成「有成交」會把一個沒發生的決策計入
    加值統計。區間下緣以下成交是更好的價格，仍算成交。
    """
    if not isinstance(entry_range, (list, tuple)) or not len(entry_range):
        return True
    return float(entry_px) <= float(max(entry_range))


def realized_return(entry, exit_, *, entry_notional=DEFAULT_POSITION_NOTIONAL,
                    fee_discount=1.0):
    return round_trip_return(
        entry, exit_, entry_notional=entry_notional, fee_discount=fee_discount)


def realized(engine, df, horizon, *, entry_notional=DEFAULT_POSITION_NOTIONAL,
             fee_discount=1.0):
    """把每個決策接上實際報酬；未滿 horizon 的標成 pending、跳空穿過區間的標成 no_fill。"""
    ids = sorted(df["stock_id"].astype(str).unique())
    lo = pd.to_datetime(df["date"]).min() - pd.Timedelta(days=10)
    with engine.connect() as c:
        px = pd.read_sql(text("select stock_id, date, open, close from market.price "
                              "where date >= :lo and stock_id = any(:ids)"), c,
                         params={"lo": lo.date(), "ids": ids}, parse_dates=["date"])
        cal = pd.DatetimeIndex(sorted(r[0] for r in c.execute(text(
            "select distinct date from market.price where date >= :lo"),
            {"lo": lo.date()}).fetchall()))
    if px.empty:
        raise SystemExit("market.price 查不到這些標的——先確認 DATABASE_URL 與資料是否已更新")
    op = px.pivot(index="date", columns="stock_id", values="open").astype(float)
    cl = px.pivot(index="date", columns="stock_id", values="close").astype(float)
    adj = load_factors(engine, cl.index, cl.columns)
    # 區間比對用**未還原**開盤：`entry_range` 是判斷當下的名目價，拿還原後的開盤去比，
    # 除權息後會把「開盤其實高於上界、沒成交」的算成成交。報酬仍用前復權價。
    op_raw = op
    op, cl = op * adj, cl * adj

    out = []
    for _, r in df.iterrows():
        e_d, x_d, left = window(cal, r["date"], horizon, r.get("decided_at"))
        rec = {"pending": True, "r": np.nan, "left": left, "no_fill": False,
               "entry_date": pd.NaT, "entry_px": np.nan}
        sid = str(r["stock_id"])
        if e_d is not None and sid in op.columns and pd.notna(op.at[e_d, sid]):
            entry = float(op.at[e_d, sid])
            raw_open = float(op_raw.at[e_d, sid])
            if not fill_ok(raw_open, r.get("entry_range")):
                rec.update(pending=False, no_fill=True, entry_date=e_d, entry_px=raw_open)
            else:
                px_out = cl.at[x_d, sid]
                if pd.isna(px_out):                      # 期間停止交易 → 最後成交價結算
                    px_out = cl[sid].loc[:x_d].dropna().iloc[-1]
                rec = {"pending": False, "no_fill": False, "left": 0,
                       "r": realized_return(entry, px_out, entry_notional=entry_notional,
                                            fee_discount=fee_discount),
                       "entry_date": e_d, "entry_px": entry}
        out.append(rec)
    result = pd.concat([df.reset_index(drop=True), pd.DataFrame(out)], axis=1)
    result.attrs["calendar"] = cal
    return result


def selection_lift_ci(events, calendar, n=2000, block=60, seed=42):
    """同一批日曆區塊內重算 enter 與全收均值差；資料不足回 ``None``。"""
    rows = events.loc[:, ["entry_date", "verdict", "r"]].dropna()
    rows = rows[np.isfinite(rows["r"].astype(float))]
    calendar = pd.Index(calendar)
    if (n < 2 or block < 1 or len(calendar) < block * 2 or rows.empty
            or not (rows["verdict"] == "enter").any()
            or not rows["entry_date"].isin(calendar).all()
            or rows["entry_date"].nunique() < 2):
        return None
    if not calendar.is_unique or not calendar.is_monotonic_increasing:
        raise ValueError("calendar must be an ordered, unique full session index")
    positions = calendar.get_indexer(pd.Index(rows["entry_date"].unique()))
    if positions.max() - positions.min() < block:
        return None

    by_day = {
        day: (group["r"].to_numpy(float),
              group["verdict"].eq("enter").to_numpy(bool))
        for day, group in rows.groupby("entry_date")
    }
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(len(calendar) / block))
    diffs = []
    for _ in range(n):
        values, selected = [], []
        sampled = 0
        for start in rng.integers(0, len(calendar), size=n_blocks):
            for offset in range(block):
                if sampled == len(calendar):
                    break
                pair = by_day.get(calendar[(int(start) + offset) % len(calendar)])
                if pair is not None:
                    values.extend(pair[0])
                    selected.extend(pair[1])
                sampled += 1
        values, selected = np.asarray(values), np.asarray(selected, bool)
        if len(values) and selected.any():
            diffs.append(values[selected].mean() - values.mean())
    if len(diffs) < 2:
        return None
    if np.all(np.asarray(diffs) == 0):
        return 0.0, 0.0
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def _portfolio_signals(rows, index, columns=None):
    """把已到期且成交的決策轉成 `simulate` 的訊號面板，回傳 (訊號面板, conf_map, 跳過筆數)。

    `simulate` 是「昨天收盤的訊號、今天開盤買進」，所以訊號日必須是 `entry_date` 在 `index`
    裡的**前一個交易日**，這樣組合臂才會在與逐筆路徑（`window()`，已含 `decided_at`）相同的
    進場日成交。用 `r['date']` 當訊號日會無視 `decided_at`：判斷在進場日當天上午才做完
    （2408：08-14 09:40 決定、開盤 532 已高於區間上界 525），組合臂卻照樣用那天開盤買進。

    `conf_map` 以 (訊號日, stock_id) 為鍵，與 `simulate` 呼叫排序函式的 (prev, s) 一致；
    仍以 `r['date']` 為鍵會全部查成 0、排序靜默失效。`entry_date` 不在 `index`（含缺值）
    或就是 `index[0]`（沒有前一個交易日可當訊號日）的決策不進組合，回傳跳過筆數讓呼叫端揭露。
    """
    index = pd.DatetimeIndex(index)
    if columns is None:
        columns = sorted(rows["stock_id"].astype(str).unique()) if len(rows) else []
    sig = pd.DataFrame(False, index=index, columns=columns)
    conf, skipped = {}, 0
    for _, r in rows.iterrows():
        sid = str(r["stock_id"])
        e_d = r.get("entry_date")
        pos = index.get_indexer([e_d])[0] if pd.notna(e_d) else -1
        if pos < 1 or sid not in sig.columns:
            skipped += 1
            continue
        sig_day = index[pos - 1]
        sig.at[sig_day, sid] = True
        c = r.get("confidence")
        conf[(sig_day, sid)] = 0.0 if c is None or pd.isna(c) else float(c)
    return sig, conf, skipped


def paired_portfolio(df, engine, horizon, slots, *, fee_discount=1.0):
    """把決策放回組合：同樣 `slots` 個空位，比「全收」與「只收 enter」兩本帳。

    事件均值不是可投資報酬——20 個同日同題材的訊號可以讓均值很漂亮，但真實帳戶只拿得到
    `slots` 檔。這一段才是「AI 這層有沒有加值」的可成交版本。

    `df` 必須是已到期且成交的決策（含 `entry_date`），訊號日由 `_portfolio_signals` 推算。
    """
    from portfolio_walkforward import simulate           # 延遲載入，避免循環相依
    ids = sorted(df["stock_id"].astype(str).unique())
    lo = pd.to_datetime(df["date"]).min() - pd.Timedelta(days=10)
    with engine.connect() as c:
        px = pd.read_sql(text("select stock_id, date, open, close from market.price "
                              "where date >= :lo and stock_id = any(:ids)"), c,
                         params={"lo": lo.date(), "ids": ids}, parse_dates=["date"])
    op = px.pivot(index="date", columns="stock_id", values="open").astype(float)
    cl = px.pivot(index="date", columns="stock_id", values="close").astype(float)
    adj = load_factors(engine, cl.index, cl.columns)
    piv = {"open": op * adj, "close": cl * adj}
    _, conf, skipped = _portfolio_signals(df, cl.index, cl.columns)
    if skipped:
        print(f"（可成交口徑：{skipped} 筆決策的進場日不在價格面板內或為面板首日，"
              f"沒有前一交易日可當訊號日，未納入組合）")

    order = lambda d, sid: conf.get((d, sid), 0.0)       # noqa: E731 - 依 confidence 排序
    res = {}
    for label, rows in (("全收", df), ("只收 enter", df[df["verdict"] == "enter"])):
        if not len(rows):
            continue
        sig, _, _ = _portfolio_signals(rows, cl.index, cl.columns)
        eq, tr, _, _ = simulate(piv, sig, None, None, horizon, slots,
                                cl.index[0], cl.index[-1], rank=order,
                                fee_discount=fee_discount)
        res[label] = (eq, tr)
    return res


def _adj_close_panel(engine, ids, days=150):
    """近 ``days`` 曆日的前復權收盤面板（index=date、columns=stock_id）。

    「現價」與失效條件裡的均線**必須落在同一個復權基準**上：`market.price` 是未還原價
    （見 `market_data/AGENTS.md`），拿未還原價算的 MA 去比還原後的現價，只要區間橫跨一次
    除權息就差一個因子——而且不會報錯，只會給出一個看起來合理的錯判。150 曆日約 100 個
    交易日，夠算到 MA60。

    **刻意不 ffill**：面板的 index 是多檔股票的**聯集**交易日，某檔停牌或那天沒成交時
    ffill 會補出一根合成 K 棒。MA 取「最後 n 列」時就會吃到合成值、同時把最舊的一根真實
    K 棒推出視窗——算出來的不是 n 根真實資料的均線，而且照樣不會報錯。要 ffill 的消費端
    自己做（`_last_close`），需要真實 K 棒的消費端 `dropna()`（`_ma_check`）。
    """
    if not ids:
        return None
    with engine.connect() as c:
        px = pd.read_sql(text(
            "select stock_id, date, close from market.price "
            "where stock_id = any(:ids) and date >= (select max(date) - "
            "(:days * interval '1 day') from market.price)"),
            c, params={"ids": list(ids), "days": int(days)}, parse_dates=["date"])
    if px.empty:
        return None
    cl = px.pivot(index="date", columns="stock_id", values="close").astype(float)
    adj = load_factors(engine, cl.index, cl.columns)
    return cl * adj


def _last_close(panel):
    """各標的最近一個有成交的交易日的前復權收盤，給「現價 vs 進場區間」用。

    停牌或當天無量的個股取**最後一個有效報價**（等價於原本的 ffill 語意），與 `_ma_check`
    比較用的 `px` 同源——兩邊都是「最後一根真實 K 棒」。
    """
    if panel is None or panel.empty:
        return {}
    last = panel.ffill().iloc[-1]
    return {s: round(float(v), 2) for s, v in last.items() if pd.notna(v)}


# `invalidation` 是自由文字，裡面的均線門檻寫的是**做判斷當天**的值（例：`跌破MA20(79.85)`）。
# MA 每天在動，隔幾天照舊值判就會判錯：2026-07-28 實測 6166 收 137.0，照日誌的 `MA10(136.7)`
# 看是「未跌破」，但當天真正的 MA10 已經漂到 138.70，其實**已經跌破**。所以要即時重算。
#
# `(?<![A-Za-z])` 是必要的：沒有它 `跌破EMA10(136.7)` 會被讀成 `MA10`（指數移動平均與簡單
# 移動平均是兩個不同的門檻，重算成 SMA 等於換了條件還宣稱驗過）。數值允許千分位逗號——
# `MA20(1,234.5)` 少了它只會匹配到裸 `MA20`，靜默丟掉門檻連翻轉警告都不會出現。
_MA_RE = re.compile(r"(?<![A-Za-z])MA(\d+)\s*(?:[（(]\s*([\d,.]+)\s*[）)])?")


def _ma_check(panel, stock_id, invalidation):
    """把 `invalidation` 文字裡每個 `MA<n>` 門檻換算成今天的值，回傳可印的註記行。

    **只處理均線**：`SCFI 連續第三週下跌`、`法人由買轉賣`、`費半連續兩日下跌逾2%` 這些要
    外部資料或人工判斷，這裡不假裝能自動判定——把沒驗的條件印成「未觸發」比不印更糟。
    """
    if panel is None or stock_id not in panel.columns:
        return []
    s = panel[stock_id].dropna()
    if not len(s):
        return []
    px = float(s.iloc[-1])
    out = []
    for n_str, written in _MA_RE.findall(invalidation or ""):
        n = int(n_str)
        if len(s) < n:
            out.append(f"MA{n}：歷史只有 {len(s)} 根，不足以重算")
            continue
        # `s` 已 dropna，所以這 n 列都是真實 K 棒（面板刻意不 ffill，見 `_adj_close_panel`）
        now = float(s.iloc[-n:].mean())
        broke = px < now
        note = f"MA{n} 現在 {now:.2f}"
        old = float(written.replace(",", "")) if written else None
        if old is not None:
            note += f"（日誌寫的是 {old:.2f}）"
        note += f"，現價 {px:.2f} " + ("**已跌破**" if broke else "未跌破")
        # 只有「照舊值會得到相反結論」才是真的坑，明確標出來
        if old is not None and broke != (px < old):
            note += "　⚠ 照日誌裡的舊值會判成相反結論"
        out.append(note)
    return out


def summarize(r, label):
    if not len(r):
        return {"組": label, "筆數": 0}
    return {"組": label, "筆數": len(r), "均值": f"{r.mean() * 100:+.2f}%",
            "中位": f"{r.median() * 100:+.2f}%", "勝率": f"{(r > 0).mean() * 100:.1f}%",
            "P(≥30%)": f"{(r >= .3).mean() * 100:.1f}%",
            "P(≤-20%)": f"{(r <= -.2).mean() * 100:.1f}%"}


def main(argv=None):
    p = argparse.ArgumentParser(description="回驗波段研究判斷（Brier + 加值差值）")
    p.add_argument("--log", default=str(LOG))
    p.add_argument("--horizon", type=int, default=60, help="持有交易日數（與量測一致）")
    p.add_argument("--slots", type=int, default=5,
                   help="配對組合驗證的空位數（與 portfolio_walkforward 一致）")
    p.add_argument("--entry-notional", type=float, default=DEFAULT_POSITION_NOTIONAL,
                   help="每筆進場名目本金（影響最低手續費）")
    p.add_argument("--fee-discount", type=float, default=1.0,
                   help="券商手續費折扣乘數")
    a = p.parse_args(argv)
    if a.entry_notional <= 0:
        p.error("--entry-notional must be positive")
    if a.fee_discount < 0:
        p.error("--fee-discount must be non-negative")

    path = Path(a.log)
    if not path.exists():
        print(f"找不到 {path}——`tw-swing-research` 技能每做一次判斷會追加一行到這裡"
              f"（見 journal/README.md）。還沒有判斷就沒有東西可回驗。")
        return 0
    df = read_log(path)
    excluded = df.attrs.get("closed_excluded", 0)
    print(f"已排除 {excluded} 筆訊號日為休市日的決策（臨時休市清單／非交易日）。")
    if not len(df):
        print(f"{path} 全數 {excluded} 筆皆為休市日、已排除。" if excluded
              else f"{path} 是空的。")
        return 0
    need = {"date", "stock_id", "verdict"}
    if miss := need - set(df.columns):
        raise SystemExit(f"決策日誌缺欄位 {miss}——這些是回驗的必要欄位")
    dup = df.duplicated(subset=["date", "stock_id"], keep=False)
    if dup.any():
        raise SystemExit(f"決策日誌有重複的 (date, stock_id)，會讓同一個決策被計兩次：\n"
                         f"{df.loc[dup, ['date', 'stock_id', 'verdict']].to_string(index=False)}")
    if "decided_at" not in df.columns or df["decided_at"].isna().any():
        n = len(df) if "decided_at" not in df.columns else int(df["decided_at"].isna().sum())
        print(f"**警告：{n} 筆沒有 `decided_at`**——這些筆只能用訊號日推進場日，"
              f"無法證明判斷不是事後做的（skill 要求必填）。")

    eng = get_engine()
    df = realized(eng, df, a.horizon, entry_notional=a.entry_notional,
                  fee_discount=a.fee_discount)
    calendar = df.attrs["calendar"]
    nf = df[df["no_fill"]]
    mat, pend = df[~df["pending"] & ~df["no_fill"]], df[df["pending"]]
    print(f"決策 {len(df)} 筆　已到期 {len(mat)} 筆　未到期 {len(pend)} 筆　"
          f"跳空穿過區間未成交 {len(nf)} 筆（持有 {a.horizon} 交易日）")
    if len(pend):
        # 未到期的那些不是「等結果」而已——它們的 entry_range / invalidation 是**今天早上要看的
        # 待觸發計畫**。只印代號與剩餘天數的話，這一步就得靠人記得，而靠記憶的步驟遲早會漏。
        pv = pend.assign(剩餘交易日=pend["left"].astype("Int64"))
        panel = _adj_close_panel(eng, sorted(pend["stock_id"].astype(str).unique()))
        cur = _last_close(panel)
        pv["現價"] = [cur.get(str(s)) for s in pv["stock_id"]]
        pv["進場區間"] = [
            f"{min(r)}~{max(r)}" if isinstance(r, (list, tuple)) and len(r) else "—"
            for r in pv.get("entry_range", [None] * len(pv))
        ]
        pv["落在區間內"] = ["—" if p2 is None or "~" not in rg else
                       ("**是**" if float(rg.split("~")[0]) <= p2 <= float(rg.split("~")[1])
                        else "否")
                       for p2, rg in zip(pv["現價"], pv["進場區間"])]
        cols = ["date", "stock_id", "verdict", "剩餘交易日", "現價", "進場區間", "落在區間內"]
        print(pv[cols].to_string(index=False))
        for _, r in pv.iterrows():
            if r.get("invalidation"):
                print(f"  {r['stock_id']} 失效條件：{r['invalidation']}")
                for line in _ma_check(panel, str(r["stock_id"]), r["invalidation"]):
                    print(f"       {line}")
    if len(nf):
        print("未成交（開盤已高於建議區間上界）:")
        print(nf[["date", "stock_id", "entry_date", "entry_px"]].to_string(index=False))
    if not len(mat):
        print("\n還沒有到期且成交的決策，無法評估。")
        return 0
    thin = len(mat) < MIN_MATURED
    if thin:
        print(f"\n**已到期只有 {len(mat)} 筆（< {MIN_MATURED}）：以下全部是雜訊，"
              f"不足以判定這一層有沒有加值。下面的判定一律標為 inconclusive。**")

    ent = mat[mat["verdict"] == "enter"]
    pas = mat[mat["verdict"] == "pass"]
    print("\n=== 分布 ===")
    print(pd.DataFrame([summarize(ent["r"], "enter"), summarize(pas["r"], "pass"),
                        summarize(mat["r"], "全收（不篩選）")]).set_index("組").to_string())

    print("\n=== 加值（事件均值口徑）===")
    if len(ent):
        add = ent["r"].mean() - mat["r"].mean()
        ci = selection_lift_ci(mat, calendar)
        if ci is None:
            print(f"E[R|enter] − E[R|全收] = {add * 100:+.2f}pp"
                  "（paired calendar-block bootstrap：資料不足）→ **inconclusive**")
        else:
            lo, hi = ci
            sig_ = (not thin) and (lo > 0 or hi < 0)
            verdict = ("**inconclusive**（區間跨零或樣本不足）" if not sig_ else
                       "這一層有加值" if lo > 0 else "**這一層在扣分**")
            print(f"E[R|enter] − E[R|全收] = {add * 100:+.2f}pp"
                  f"（paired calendar-block 95% {lo * 100:+.2f}pp ~ {hi * 100:+.2f}pp）→ {verdict}")
    if len(pas):
        print(f"E[R|pass] = {pas['r'].mean() * 100:+.2f}%"
              f"　放棄 {len(pas)} 筆，其中 {(pas['r'] >= .3).sum()} 筆後來漲逾 30%（機會成本）")

    # === 可成交口徑：同樣的空位限制下，全收 vs 只收 enter ===
    try:
        arms = paired_portfolio(
            df[~df["pending"] & ~df["no_fill"]], eng, a.horizon, a.slots,
            fee_discount=a.fee_discount)
    except Exception as exc:                                  # noqa: BLE001
        arms = {}
        print(f"\n（配對組合驗證跳過：{exc}）")
    if len(arms) == 2:
        print(f"\n=== 加值（可成交口徑：{a.slots} 個空位、同日資金競爭）===")
        rows = {}
        for label, (eq, tr) in arms.items():
            rows[label] = {"期末權益": f"{eq.iloc[-1] / eq.iloc[0]:.3f}x",
                           "成交": len(tr),
                           "均值": f"{tr['r'].mean() * 100:+.2f}%" if len(tr) else "—"}
        print(pd.DataFrame(rows).T.to_string())
        print("事件均值可以被同日同題材的一堆訊號撐高，但真實帳戶只拿得到 "
              f"{a.slots} 檔——這一欄才是可投資的加值。")

    if "confidence" in mat.columns:
        cf = mat.dropna(subset=["confidence"])
        if len(cf):
            y = (cf["r"] >= 0.30).astype(float)
            c = cf["confidence"].astype(float)
            own_loss = (c - y) ** 2
            base_loss = (BASE_RATE - y) ** 2
            b, b0 = float(own_loss.mean()), float(base_loss.mean())
            ci = paired_block_bootstrap(
                pd.DataFrame({"date": cf["entry_date"], "diff": own_loss - base_loss}),
                calendar, n=2000)
            if ci is None:
                interval = "—"
                conclusion = "**inconclusive**（paired calendar blocks 不足）"
            else:
                lo, hi = ci
                interval = f"{lo:+.4f} ~ {hi:+.4f}"
                decisive = (not thin) and (lo > 0 or hi < 0)
                conclusion = ("**inconclusive**" if not decisive else
                              "**沒有比基準率準**" if lo > 0 else "比基準率準")
            print(f"\n=== confidence 校準（{len(cf)} 筆）===")
            print(f"Brier {b:.4f}　vs 一律報基準率 {BASE_RATE:.3f} 的 {b0:.4f}"
                  f"（差值 95% {interval}）→ {conclusion}")
            print(f"（基準率 {BASE_RATE:.3f} 只在訊號版本與候選母體不變時才是公平對照——"
                  f"日誌沒有記 batch 與版本，換過門檻就要重算）")
            print(f"平均 confidence {c.mean():.3f}　實際命中率 {y.mean():.3f}"
                  f"（差 {(c.mean() - y.mean()) * 100:+.1f}pp，>0 是過度自信）")
            bins = pd.cut(c, [0, .2, .3, .4, 1.0], right=False)
            g = pd.DataFrame({"conf": c, "hit": y}).groupby(bins, observed=True).agg(
                筆數=("hit", "size"), 平均conf=("conf", "mean"), 實際命中率=("hit", "mean"))
            print(g.round(3).to_string())

    if {"exp_upside", "exp_downside"} <= set(mat.columns):
        ev = mat.dropna(subset=["exp_upside", "exp_downside", "confidence"])
        if len(ev):
            pred = (ev["exp_upside"].astype(float) * ev["confidence"].astype(float)
                    + ev["exp_downside"].astype(float) * (1 - ev["confidence"].astype(float)))
            print("\n=== 期望值估計 ===")
            print(f"預測均值 {pred.mean() * 100:+.2f}%　實際均值 {ev['r'].mean() * 100:+.2f}%"
                  f"　偏差 {(pred.mean() - ev['r'].mean()) * 100:+.2f}pp")

    # === 哪一類判斷比較準：按理由的分類拆開看 ===
    # 這一段是「以後檢討怎樣比較好」的入口——它回答的不是「賺不賺」，是**哪一種理由撐得住**
    # （可延續的催化劑真的比較好嗎？「已消化」的是不是真的該躲？主題有沒有押太集中？）。
    for col, title in (("catalyst_type", "催化劑類型"), ("durable", "催化劑可否延續"),
                       ("digested", "消化程度"), ("theme", "主題"),
                       ("peer_confirm", "同業有無同步")):
        if col not in mat.columns or not mat[col].notna().any():
            continue
        sub = mat.dropna(subset=[col])
        g = sub.groupby(sub[col].astype(str))["r"].agg(
            筆數="size", 均值="mean", 勝率=lambda s: (s > 0).mean(),
            命中率=lambda s: (s >= .3).mean())
        for c2 in ("均值", "勝率", "命中率"):
            g[c2] = (g[c2] * 100).round(1)
        print(f"\n=== 按{title}拆（enter+pass 都算，看的是判斷理由不是持倉）===")
        print(g.to_string())
        if thin:
            print("（樣本不足，這張表只是先把管線接起來，別當結論）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
