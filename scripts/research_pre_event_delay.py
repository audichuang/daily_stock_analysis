#!/usr/bin/env python3
"""研究：FOMC／CPI／NFP 前一個台股交易日「正常進場」對「延後到事件後第一個交易日進場」。

驗證 skill `tw-morning-call` Step 2.5「重大事件前一天不新建部位」。事先登記與結果見
`docs/research/2026-10-28-pre-event-delay.md`；成對框架沿用 `docs/research/2026-10-26-exp-disposal-delay.md`
（`measure_signal_forward` 的突破池、成本、`paired_block_bootstrap`），這支只多了事件日對齊與兩個子組。

**事件日對齊**（三種事件同一條規則）：FOMC 決議 14:00 ET（台北次日 02:00／03:00）、CPI 與 NFP
08:30 ET（台北當日 20:30／21:30），都在美國公布日 R 的台股收盤（13:30）之後、下一個台股開盤之前。所以

- ``T`` ＝ 台股交易日中 ``date <= R`` 的最後一天：當天盤前判讀時事件還沒公布，就是規則說的「事件前一天」；
- 受影響訊號 ＝ 訊號日 D 的下一個交易日是 T（``ti + 1 == T``，正常臂在 T 開盤進場、抱著事件）；
- 延後臂 ＝ 以 T 當訊號日，T 的下一個交易日（事件後第一個交易日）開盤進場，**持有同樣 h 日**。
R 落在台股休市日時 T 往前移，規則不變。

資料（研究用快取，**不寫正式 DB**；`--fetch` 才連網，預設只讀快取）：

- FOMC：Fed 官網 2020 歷史頁（只取例會；unscheduled／cancelled 略過）＋現行行事曆頁（2021 起，
  `market_data.macro.parse_fed_calendar`）。
- CPI（rid=10）、NFP（Employment Situation，rid=50）：ALFRED release downloaddates。清單混有非首發的
  日期（CPI 每年 2 月的季節因子修訂、NFP 的更正與基準預估），一律「每個日曆月只留一個」：CPI 留當月最後一個、
  NFP 留當月第一個（`clean_release_dates`，被丟掉的日期會印出來）。
- 大局緊縮日：FRED DGS10、yfinance ``BZ=F``、``DX-Y.NYB``（與 `market_data.macro.SERIES` 同代號）。
  正式庫 `macro_series` 只從 2024 起，所以另抓快取。

stlouisfed.org 會把帶瀏覽器 UA 的請求掛住（2026-10-28 實測），所以用 requests 預設 UA。

用法（`DATABASE_URL` 由主 checkout 的 `.env` 匯出一個變數、`STORAGE_DATABASE_URL=''`；連線設唯讀）：
    uv run --frozen python scripts/research_pre_event_delay.py --fetch     # 抓快取到 ~/.cache/dsa/research/pre-event-delay/
    uv run --frozen python scripts/research_pre_event_delay.py             # h60
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_signal_forward import (  # noqa: E402
    DEFAULT_POSITION_NOTIONAL,
    HIT_THRESHOLD,
    describe,
    paired_block_bootstrap,
)
from tw_trade_costs import round_trip_return  # noqa: E402

DEFAULT_CACHE = Path.home() / ".cache" / "dsa" / "research" / "pre-event-delay"  # 子目錄：research/ 與其他研究共用
ALFRED_URL = "https://alfred.stlouisfed.org/release/downloaddates?rid={rid}&ff=txt"
ALFRED_RIDS = {"cpi": 10, "nfp": 50}
# 同月多個日期時留哪一個：CPI 的 2 月額外日期在首發之前（季節因子修訂）；NFP 的在之後（更正、基準預估）
RELEASE_KEEP = {"cpi": "last", "nfp": "first"}
FED_HISTORICAL_URL = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={start}"
MACRO_IDS = ("FRED:DGS10", "BZ=F", "DX-Y.NYB")
MACRO_LOOKBACK = 20         # 「20 日變化」：各序列自己的第 20 個前一筆觀測
MIN_EVENTS = 30             # 事先登記：配對 n < 30 一律 inconclusive
# C8 補遺：借券賣出／融券暫時管制期（以訊號日判定，只分列、不剔除）
C8_START, C8_END = pd.Timestamp("2025-04-07"), pd.Timestamp("2025-05-23")
_HIST_HEADING = re.compile(r"<h5[^>]*>\s*([A-Za-z]+)\s+([0-9]+(?:-[0-9]+)?)\s*([^<]*?)Meeting\s*-\s*(\d{4})\s*</h5>")


# ── 事件日 ─────────────────────────────────────────────────────────────


def parse_alfred_dates(text):
    """ALFRED downloaddates 的 txt：表頭之後每行一個 ``YYYY-MM-DD``。抓不到任何日期就 raise。"""
    dates = [datetime.date.fromisoformat(m) for m in
             re.findall(r"^(\d{4}-\d{2}-\d{2})\s*$", text, re.M)]
    if not dates:
        raise ValueError("ALFRED 回應沒有日期列（端點可能改版）")
    return sorted(set(dates))


def clean_release_dates(dates, keep):
    """每個日曆月只留一個公布日；``keep`` 為 ``first``／``last``。回 ``(留下, 丟掉)``。"""
    if keep not in ("first", "last"):
        raise ValueError(keep)
    by_month = {}
    for d in sorted(dates):
        by_month.setdefault((d.year, d.month), []).append(d)
    kept, dropped = [], []
    for ds in by_month.values():
        pick = ds[0] if keep == "first" else ds[-1]
        kept.append(pick)
        dropped.extend(d for d in ds if d != pick)
    return sorted(kept), sorted(dropped)


def parse_fed_historical(html):
    """Fed 歷史頁（``fomchistorical2020.htm``）的例會決議日（會議最後一天）；
    unscheduled 與 cancelled 略過（2020-03 的 17-18 日例會改成 15 日臨時會）。"""
    from market_data.macro import _MONTHS

    out = []
    for month_text, day_text, note, year in _HIST_HEADING.findall(html):
        if re.search(r"unscheduled|cancel", note, re.I):
            continue
        month = _MONTHS.get(month_text.lower())
        if month is None:
            continue
        out.append(datetime.date(int(year), month, int(day_text.split("-")[-1])))
    return sorted(set(out))


def pre_event_sessions(index, releases):
    """美國公布日 → 「事件前一個台股交易日」T 在 ``index`` 的位置。

    ``releases``：``{event_type: [date, ...]}``。回 ``{T 位置: 事件類型集合}``；T 是 ``date <= R``
    的最後一個交易日（公布在台股收盤後），且 T 之後面板還要有下一個交易日，否則延後臂不存在、略過。"""
    index = pd.DatetimeIndex(index)
    out = {}
    for kind, dates in releases.items():
        for r in dates:
            t = int(index.searchsorted(pd.Timestamp(r), side="right")) - 1
            if t < 0 or t + 1 >= len(index):
                continue
            out.setdefault(t, set()).add(kind)
    return out


def pre_event_context(ev, t_map):
    """事件是否受影響（訊號日下一個交易日＝T）。回與 ``ev`` 同索引的 DataFrame：
    ``affected``、``t_idx``（延後臂的訊號日位置）、``types``（'cpi,fomc' 之類）、``c8``。"""
    t_idx = ev["ti"].astype(int) + 1
    hit = t_idx.map(lambda t: t in t_map)
    types = t_idx.map(lambda t: ",".join(sorted(t_map[t])) if t in t_map else "")
    dates = pd.DatetimeIndex(ev["date"])
    return pd.DataFrame({"affected": hit.to_numpy(dtype=bool),
                         "t_idx": t_idx.where(hit).to_numpy(dtype=float),
                         "types": types.to_numpy(),
                         "c8": ((dates >= C8_START) & (dates <= C8_END))}, index=ev.index)


def delayed_arm_returns(ev, ctx, ret, *, entry_notional=DEFAULT_POSITION_NOTIONAL, fee_discount=1.0):
    """受影響事件在延後臂（以 T 為訊號日）的淨報酬；超出面板或無價格回 NaN，配對時剔除。"""
    hit = ev.index[ctx["affected"].to_numpy(dtype=bool)]
    n = len(ret.index)
    vals = []
    for i in hit:
        t, sid = int(ctx.at[i, "t_idx"]), ev.at[i, "stock_id"]
        r = ret.iat[t, ret.columns.get_loc(sid)] if t < n else np.nan
        vals.append(np.nan if pd.isna(r) else round_trip_return(
            1.0, 1.0 + float(r), entry_notional=entry_notional, fee_discount=fee_discount))
    return pd.Series(vals, index=hit, dtype=float)


def trade_max_drawdown(open_, close, signal_idx, sid, h):
    """單筆持有期間的最大回撤（毛、不含成本）：訊號日 ``signal_idx`` 的下一列開盤進場，
    逐日收盤對「進場價與之前收盤的最高點」的最大跌幅，到第 ``signal_idx + h`` 列為止。"""
    c = close.columns.get_loc(sid)
    entry = open_.iat[signal_idx + 1, c] if signal_idx + 1 < len(open_.index) else np.nan
    path = close.iloc[signal_idx + 1: signal_idx + h + 1, c].dropna().to_numpy(dtype=float)
    if pd.isna(entry) or not len(path):
        return np.nan
    peak = np.maximum.accumulate(np.concatenate([[float(entry)], path]))[1:]
    return float(np.min(path / peak - 1.0))


# ── 大局緊縮日 ─────────────────────────────────────────────────────────


def tightening_flags(macro, sessions, lookback=MACRO_LOOKBACK):
    """每個台股交易日盤前可見的「DGS10、Brent、DXY 的 20 日變化同為正」。

    ``macro``：欄位 ``series_id``／``date``／``value``。台股 S 日盤前只看得到美國日期 < S 的資料
    （嚴格小於：美國 S 日的收盤在台北 S+1 凌晨）。三個序列任一缺值就是 False（不猜）。"""
    # merge_asof 要求兩邊時間解析度相同（面板是 [us]、CSV 讀進來可能是 [s]），統一成 [ns]
    sessions = pd.DatetimeIndex(sessions).astype("datetime64[ns]")
    flag = pd.Series(True, index=sessions)
    for sid in MACRO_IDS:
        s = (macro[macro["series_id"] == sid]
             .assign(date=lambda x: pd.to_datetime(x["date"]).astype("datetime64[ns]"))
             .sort_values("date"))
        if not len(s):
            return pd.Series(False, index=sessions)
        s = s.assign(chg=s["value"] - s["value"].shift(lookback))[["date", "chg"]]
        m = pd.merge_asof(pd.DataFrame({"session": sessions}), s, left_on="session",
                          right_on="date", allow_exact_matches=False)
        flag &= (m["chg"] > 0).to_numpy()
    return flag


# ── 判準 ───────────────────────────────────────────────────────────────


def pre_event_verdict(n, ci_mean, ci_hit, min_events=MIN_EVENTS):
    """事先登記：n ≥ 下限，且延後−正常的均值差與 P(≥30%) 差兩個 95% 區間都整段 > 0 才「支持」；
    兩個區間都整段 < 0 記「較差」；其餘（含區間缺）一律 inconclusive。"""
    if n < min_events or ci_mean is None or ci_hit is None:
        return "inconclusive"
    if ci_mean[0] > 0 and ci_hit[0] > 0:
        return "支持"
    if ci_mean[1] < 0 and ci_hit[1] < 0:
        return "較差"
    return "inconclusive"


def paired_summary(pair, calendar, h, n_boot, seed):
    """``pair``：``date``（calendar 位置）、``arm``、``base``。回 dict（含兩個 CI 與判定）。"""
    n = len(pair)
    out = {"n": n, "d_mean": np.nan, "d_hit": np.nan, "ci_mean": None, "ci_hit": None}
    if n:
        dh = ((pair["arm"] >= HIT_THRESHOLD).astype(float)
              - (pair["base"] >= HIT_THRESHOLD).astype(float))
        out.update(d_mean=float((pair["arm"] - pair["base"]).mean()), d_hit=float(dh.mean()),
                   base_mean=float(pair["base"].mean()), arm_mean=float(pair["arm"].mean()))
        if n_boot:
            out["ci_mean"] = paired_block_bootstrap(pair.assign(diff=pair["arm"] - pair["base"]),
                                                    calendar, n=n_boot, block=h, seed=seed)
            out["ci_hit"] = paired_block_bootstrap(pair.assign(diff=dh), calendar,
                                                   n=n_boot, block=h, seed=seed)
    out["verdict"] = pre_event_verdict(n, out["ci_mean"], out["ci_hit"])
    return out


def _fmt_ci(c):
    return "無區間" if c is None else f"{c[0] * 100:+.2f} ~ {c[1] * 100:+.2f}"


def report(ev, ctx, arm, piv, h, *, tight=None, n_boot=2000, seed=42):
    """印出主檢定與子組；回摘要 dict。"""
    cal = np.arange(len(piv["close"].index))
    aff = ev[ctx["affected"]]
    actx = ctx.loc[aff.index]
    pair = pd.DataFrame({"date": aff["ti"], "arm": arm.reindex(aff.index), "base": aff["r"],
                         "types": actx["types"], "c8": actx["c8"],
                         "t_idx": actx["t_idx"]}).dropna(subset=["arm", "base"])
    print(f"\n=== 事件前一日延後進場（h={h}）===")
    print(f"池事件 {len(ev)} 個；受影響（訊號日下一個交易日＝事件前一個台股交易日）{len(aff)} 個"
          f"（{len(aff) / max(len(ev), 1) * 100:.1f}%）；進入配對 {len(pair)} 個、"
          f"延後臂無報酬（右端截斷／無價）而漏掉 {len(aff) - len(pair)} 個")
    for kind in ("fomc", "cpi", "nfp"):
        print(f"  含 {kind}: {int(actx['types'].str.contains(kind).sum())} 個")

    if tight is not None:
        # 緊縮旗標以正常臂的進場日（T）盤前可見的資料判定
        pair["tight"] = [bool(tight.iat[int(t)]) for t in pair["t_idx"]]
    rows = [describe(aff, "受影響·正常（全部）"),
            describe(pair.assign(r=pair["base"]), "受影響·正常（配對）"),
            describe(pair.assign(r=pair["arm"]), "受影響·延後（配對）"),
            describe(ev[~ctx["affected"]], "未受影響")]
    for label, mask in (("C8 管制期（2025-04-07～05-23）", pair["c8"]),
                        ("大局緊縮日", pair.get("tight"))):
        if mask is None or not mask.any():
            continue
        sub = pair[mask.astype(bool)]
        rows.append(describe(sub.assign(r=sub["base"]), f"{label}·正常"))
        rows.append(describe(sub.assign(r=sub["arm"]), f"{label}·延後"))
    print(pd.DataFrame(rows).set_index("組").to_string())

    # 單筆持有期最大回撤（毛）：正常臂以 D 為訊號日、延後臂以 T 為訊號日
    o, c = piv["open"], piv["close"]
    sid = ev.loc[pair.index, "stock_id"]
    pair["mdd_base"] = [trade_max_drawdown(o, c, int(d), s, h) for d, s in zip(pair["date"], sid)]
    pair["mdd_arm"] = [trade_max_drawdown(o, c, int(t), s, h) for t, s in zip(pair["t_idx"], sid)]
    print(f"\n單筆持有期最大回撤（毛，配對 {len(pair)} 筆）：正常 均值 {pair['mdd_base'].mean() * 100:+.2f}%"
          f"／中位 {pair['mdd_base'].median() * 100:+.2f}%／最差 {pair['mdd_base'].min() * 100:+.1f}%；"
          f"延後 均值 {pair['mdd_arm'].mean() * 100:+.2f}%／中位 {pair['mdd_arm'].median() * 100:+.2f}%"
          f"／最差 {pair['mdd_arm'].min() * 100:+.1f}%")

    summary = {"n_pool": len(ev), "n_affected": len(aff), "n_pair": len(pair),
               "mdd_base_mean": float(pair["mdd_base"].mean()) if len(pair) else np.nan,
               "mdd_arm_mean": float(pair["mdd_arm"].mean()) if len(pair) else np.nan,
               "groups": {}}
    print(f"\n成對差（延後 − 正常；同一批事件、持有長度相同；block={h}、{n_boot} 次、seed={seed}）：")
    groups = [("全部（主判準）", pd.Series(True, index=pair.index))]
    groups += [(k, pair["types"].str.contains(k)) for k in ("fomc", "cpi", "nfp")]
    groups += [("C8 管制期", pair["c8"]), ("非 C8", ~pair["c8"])]
    if "tight" in pair:
        groups += [("大局緊縮日（子檢定）", pair["tight"]), ("非緊縮日", ~pair["tight"])]
    for label, mask in groups:
        s = paired_summary(pair[mask.astype(bool)], cal, h, n_boot, seed)
        summary["groups"][label] = s
        print(f"  {label}: n={s['n']}  均值差 {s['d_mean'] * 100:+.2f}pp（95% {_fmt_ci(s['ci_mean'])}）  "
              f"P(≥30%) 差 {s['d_hit'] * 100:+.1f}pp（95% {_fmt_ci(s['ci_hit'])}）→ {s['verdict']}")
    print("（只有「全部」與「大局緊縮日」是事先登記的檢定；分事件類型與 C8 只描述）")
    return summary


# ── 快取 ───────────────────────────────────────────────────────────────


def fetch(cache, start):
    """抓事件日與總經序列到 ``cache``（覆寫）。requests 預設 UA（理由見模組說明）。"""
    import requests

    from market_data.macro import FED_CALENDAR_URL, parse_fred_csv, yf_rows

    cache.mkdir(parents=True, exist_ok=True)

    def get(url):
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        return r.text

    (cache / "fomchistorical2020.htm").write_text(get(FED_HISTORICAL_URL.format(year=2020)), encoding="utf-8")
    (cache / "fomccalendars.htm").write_text(get(FED_CALENDAR_URL), encoding="utf-8")
    for kind, rid in ALFRED_RIDS.items():
        (cache / f"alfred_{kind}.txt").write_text(get(ALFRED_URL.format(rid=rid)), encoding="utf-8")
    import yfinance as yf

    rows = parse_fred_csv("FRED:DGS10", get(FRED_CSV_URL.format(id="DGS10", start=start)))
    for sid in MACRO_IDS[1:]:
        hist = yf.Ticker(sid).history(start=str(start), auto_adjust=False)["Close"]
        rows.extend(yf_rows(sid, hist))
    pd.DataFrame(rows)[["series_id", "date", "value"]].to_csv(cache / "macro.csv", index=False)
    print(f"快取寫入 {cache}")


def load_releases(cache, start, end):
    from market_data.macro import parse_fed_calendar

    fomc = parse_fed_historical((cache / "fomchistorical2020.htm").read_text(encoding="utf-8"))
    fomc += [d for d in parse_fed_calendar((cache / "fomccalendars.htm").read_text(encoding="utf-8"))
             if d.year >= 2021]
    out = {"fomc": sorted(set(fomc))}
    for kind in ALFRED_RIDS:
        dates = parse_alfred_dates((cache / f"alfred_{kind}.txt").read_text(encoding="utf-8"))
        kept, dropped = clean_release_dates(dates, RELEASE_KEEP[kind])
        lo, hi = pd.Timestamp(start).date(), pd.Timestamp(end).date()
        out[kind] = [d for d in kept if lo <= d <= hi]
        print(f"{kind}: ALFRED {len(dates)} 個日期，每月留一個後丟掉 "
              f"{[str(d) for d in dropped if lo <= d <= hi]}")
    lo, hi = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    out["fomc"] = [d for d in out["fomc"] if lo <= d <= hi]
    for k, v in out.items():
        print(f"{k}: 樣本窗內 {len(v)} 個公布日（{v[0]} ~ {v[-1]}）")
    return out


# ── 主程式 ─────────────────────────────────────────────────────────────


def build_pool(a):
    """與 `measure_signal_forward.main` 相同的突破池（同一組函式與預設門檻）；連線唯讀。"""
    from sqlalchemy import event

    from market_data.adjust import is_common_stock
    from market_data.db import get_engine
    from measure_signal_forward import build_signals, forward_returns, load, pit_revenue_panel, to_events

    eng = get_engine()

    @event.listens_for(eng, "connect")
    def _read_only(dbapi_conn, _rec):  # noqa: ARG001 — 每條新連線都設成唯讀交易
        cur = dbapi_conn.cursor()
        cur.execute("SET default_transaction_read_only = on")
        cur.close()

    eng.dispose()  # 丟掉監聽器掛上前可能已建立的連線
    piv, rv, _ = load(eng, a.start, a.end)
    keep = [s for s in piv["close"].columns if is_common_stock(s)]
    piv = {k: v[keep] for k, v in piv.items()}
    yoy = pit_revenue_panel(rv, piv["close"].index, piv["close"].columns)
    sig, extra = build_signals(piv, yoy, a.min_turnover * 1e8, a.d5, a.vol_lo, a.vol_hi, a.yoy)
    sig.loc[:pd.Timestamp(a.start)] = False
    ret, _ = forward_returns(piv, a.horizon, "last")
    _, ev = to_events(sig, ret, a.horizon, {k: extra[k] for k in ("d5", "vol_r")})
    return piv, ret, ev


def main(argv=None):
    p = argparse.ArgumentParser(description="FOMC／CPI／NFP 前一日延後進場研究（突破池）")
    p.add_argument("--fetch", action="store_true", help="連網抓事件日與總經序列到快取後結束")
    p.add_argument("--cache-dir", default=str(DEFAULT_CACHE), help="研究快取目錄")
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default="2026-07-24")
    p.add_argument("--horizon", type=int, default=60)
    p.add_argument("--min-turnover", type=float, default=2.0, help="日均額門檻（億）")
    p.add_argument("--d5", type=float, default=0.05)
    p.add_argument("--vol-lo", type=float, default=1.3)
    p.add_argument("--vol-hi", type=float, default=2.0)
    p.add_argument("--yoy", type=float, default=20.0)
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--bootstrap-seed", type=int, default=42)
    a = p.parse_args(argv)
    cache = Path(a.cache_dir).expanduser()
    if a.fetch:
        fetch(cache, (pd.Timestamp(a.start) - pd.Timedelta(days=120)).date())
        return 0

    # 公布日取到 end + h 的緩衝不需要：受影響訊號的 T 一定 ≤ end 的下一個交易日
    releases = load_releases(cache, a.start, (pd.Timestamp(a.end) + pd.Timedelta(days=10)).date())
    piv, ret, ev = build_pool(a)
    index = piv["close"].index
    flat = -round_trip_return(1.0, 1.0, entry_notional=DEFAULT_POSITION_NOTIONAL)
    print(f"樣本 {a.start} ~ {a.end}　h={a.horizon}　池事件 {len(ev)} 個　平盤來回成本 {flat * 100:.3f}%")
    ctx = pre_event_context(ev, pre_event_sessions(index, releases))
    arm = delayed_arm_returns(ev, ctx, ret)
    macro = pd.read_csv(cache / "macro.csv", parse_dates=["date"])
    tight = tightening_flags(macro, index)
    in_win = (index >= pd.Timestamp(a.start)) & (index <= pd.Timestamp(a.end))
    print(f"大局緊縮日（盤前可見 DGS10、Brent、DXY 20 日變化同為正）：樣本窗 {int(in_win.sum())} 個交易日中 "
          f"{int(tight[in_win].sum())} 個（{tight[in_win].mean() * 100:.1f}%）")
    report(ev, ctx, arm, piv, a.horizon, tight=tight, n_boot=a.bootstrap, seed=a.bootstrap_seed)
    # 對抗檢查（事後加、只描述）：未受影響事件也晚一天進場，看差距是不是「晚一天」本身而非事件
    unaff = ~ctx["affected"]
    pctx = pd.DataFrame({"affected": unaff, "t_idx": (ev["ti"] + 1).astype(float)}, index=ev.index)
    p_arm = delayed_arm_returns(ev, pctx, ret)
    p_pair = pd.DataFrame({"date": ev.loc[unaff, "ti"], "arm": p_arm,
                           "base": ev.loc[unaff, "r"]}).dropna(subset=["arm", "base"])
    s = paired_summary(p_pair, np.arange(len(index)), a.horizon, a.bootstrap, a.bootstrap_seed)
    print(f"\n安慰劑（未受影響事件同樣晚一天進場，事後加、只描述）: n={s['n']}  均值差 {s['d_mean'] * 100:+.2f}pp"
          f"（95% {_fmt_ci(s['ci_mean'])}）  P(≥30%) 差 {s['d_hit'] * 100:+.1f}pp（95% {_fmt_ci(s['ci_hit'])}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
