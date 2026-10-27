#!/usr/bin/env python3
"""回驗 skill `tw-morning-call` 的盤前判讀：預估開盤缺口準不準、regime 標籤對不對得上定義。

讀 `journal/morning-calls.jsonl`（不改它），對每個已收盤的判讀日算出實際結果，
`--append` 時以 date 為鍵追加到 `journal/morning-calls-outcomes.jsonl`（append-only，同一天不重寫）。
預測與結果分兩個檔、分開 commit：防竄改保證只來自「預測比結果先進版控」。

實際缺口量三種，因為每一種都有偏誤：

    gap_open_official  TWSE 官方開盤（MI_5MINS_HIST，09:00:00 第一筆）÷ 前一日收盤 − 1。
                       09:00 還沒成交的個股以昨收計，所以天生偏向 0、會讓預估看起來「高估」。
    gap_0905           09:05:00 的加權指數（MI_5MINS_INDEX）÷ 前一日收盤 − 1。多數個股已成交，
                       但混進開盤後 5 分鐘的走勢。
    gap_tx_open        台指期近月日盤開盤 ÷ 同契約前一日日盤結算價 − 1（期交所 futDataDown）。
                       不受未成交個股影響，也沒有期現貨基差，但量的是期貨。

另記 `night_spot_gap`＝夜盤收盤 ÷ 前一日現貨收盤 − 1，也就是 skill 公式「用對數字」時該得到的值；
`gap_expected` 與它的差是**輸入錯誤**（抄錯夜盤、用了不含美股的 21:30 前報價），與它對實際的差才是公式本身的誤差。

regime 只驗得了 breadth 與 VIX 兩項（`regime_by_close`）：rotation 的「族群分化」、capitulation 的
爆量與跌停家數不在檢查內，輸出寫明。VIX 用台股收盤時已知的最近一筆（前一個美股交易日）。
action 欄只標「觀望／續抱當天大漲大跌」這類事後描述，**不是績效**。

彙總：缺口 MAE、偏差（平均誤差）、預估對實際的縮放比（過原點迴歸斜率）、方向命中率，附 bootstrap
95% 區間與 n。n < 20 或偏差區間跨零一律 inconclusive；縮放比要 n ≥ 20 且區間不含 1 才建議套用。

缺口主口徑（2026-10-27 起，判讀列 `gap_basis="tx_settle"`）：`gap_expected`＝夜盤收盤 ÷ 同合約前一日日盤結算價 − 1，
對應量測 `gap_tx_open`；舊列（沒有 `gap_basis`）是「夜盤收盤 ÷ 前一日現貨收盤」，彙總時兩種口徑分開統計、不混。

機率計分（判讀列有 `p_close_up`／`p_oc_up`／`p_gap_up`，07:30 凍結）：目標＝收盤高於前收、收盤高於官方開盤、
09:05 指數高於前收。四條基準各寫方向值與機率值（機率 Laplace 加一、252 日滾動、只用 forecast 日之前的資料）：
(a) 永遠看漲 (b) 昨日方向 (c) 07:30 前最近一個 S&P 交易日方向（`market.macro_series` 的 ^GSPC）
(d) `night_spot_gap` 符號（機率先留 null，等夜盤歷史回補）。gap_up 的 (a)(b)(c) 機率與 (b) 方向
一律留 null：歷史沒有逐日 09:05 指數，官方開盤與 09:05 不是同一個事件（符號會相反），拿來當基準是錯配；
(a) 恆看漲、(c) S&P 方向不需要 09:05 歷史，方向值照寫、照算命中差 a_i；彙總對 gap_up 印
「Brier 不可用（缺 09:05 歷史）」，close_up／oc_up 不受影響。彙總算 Brier、配對差 d_i（基準 Brier − 模型 Brier，正＝模型較好）
與 a_i（命中差），10 日 circular block bootstrap 95% 區間；n<20 或區間跨零印 inconclusive。

用法：
    uv run --env-file .env python scripts/verify_morning_calls.py            # 算、印，不寫檔
    uv run --env-file .env python scripts/verify_morning_calls.py --append   # 追加新結果（18:00 排程）
    uv run python scripts/verify_morning_calls.py --brief                    # 只讀 outcomes 檔（make morning）
"""

import argparse
import csv
import datetime as dt
import io
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CALLS = ROOT / "journal" / "morning-calls.jsonl"
OUTCOMES = ROOT / "journal" / "morning-calls-outcomes.jsonl"
HIST_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
INDEX_URL = "https://www.twse.com.tw/exchangeReport/MI_5MINS_INDEX"
TX_URL = "https://www.taifex.com.tw/cht/3/futDataDown"
MEASURES = ("gap_open_official", "gap_0905", "gap_tx_open")
MEASURE_LABEL = {"gap_open_official": "官方開盤", "gap_0905": "09:05 指數", "gap_tx_open": "台指期開盤"}
REGIMES = ("tailwind", "rotation", "broad_selloff", "capitulation")
MIN_N = 20          # 低於這個樣本數的結論一律 inconclusive（與 verify_swing_decisions 同門檻）
BIG_MOVE = 0.015    # action 事後描述用的「大漲大跌」門檻，描述性、不是績效判準
RATIO_FLOOR = 0.001  # 預估缺口絕對值低於 0.1% 時不算比值（分母太小），也不算「有資訊」的樣本
MAX_UNDEFINED = 0.05  # bootstrap 重抽有超過 5% 算不出統計量（例如全是 0 預估）就當區間不存在
PROB_TARGETS = ("close_up", "oc_up", "gap_up")
TARGET_LABEL = {"close_up": "收盤>前收", "oc_up": "收盤>開盤", "gap_up": "09:05>前收"}
BASELINES = ("a", "b", "c", "d")
NO_BASELINE = {("gap_up", k) for k in "abc"}  # 缺逐日 09:05 歷史：這幾格「機率」不可用
NO_DIR = {("gap_up", "b")}  # (b) 昨日方向也要 09:05 歷史；(a) 恆看漲、(c) 看 S&P 方向，方向值不需要
BASELINE_LABEL = {"a": "永遠看漲", "b": "昨日方向", "c": "S&P 方向", "d": "夜盤符號"}
ROLL_WINDOW = 252   # 基準機率的滾動交易日數
BLOCK = 10          # circular block bootstrap 的區塊長度（交易日）
HIST_MONTHS = 14    # 基準歷史往前抓的月數（涵蓋 252 個交易日）
DEFER_DAYS = 7      # 09:05／期貨量測暫時抓不到時，7 個曆日內延後寫入（outcome 寫了就不會再補）


# ---------- 純函式：解析 ----------

def _num(text):
    text = (text or "").replace(",", "").strip()
    if text in ("", "-", "--"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def roc_date(text):
    y, m, d = text.strip().split("/")
    return dt.date(int(y) + 1911, int(m), int(d))


def parse_hist(payload):
    """MI_5MINS_HIST 一個月的回應 → {date: (open, high, low, close)}；stat 不是 OK 回空 dict。"""
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return {}
    out = {}
    for row in payload.get("data") or []:
        vals = [_num(x) for x in row[1:5]]
        if len(vals) == 4 and None not in vals:
            out[roc_date(row[0])] = tuple(vals)
    return out


def parse_index_at(payload, day, hhmmss="09:05:00"):
    """MI_5MINS_INDEX 一天的回應 → 該時刻的加權指數；回應日期不是 ``day`` 就回 None（端點會靜默回別天）。"""
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return None
    if str(payload.get("date") or "") != day.strftime("%Y%m%d"):
        return None
    for row in payload.get("data") or []:
        if row and row[0].strip() == hhmmss:
            return _num(row[1])
    return None


def parse_tx(text):
    """期交所 futDataDown（TX）CSV → list of dict；只留單一月份契約（排除價差與週契約）。

    「盤後」列的交易日期是那段夜盤**結束**的那天：日期 d 的盤後列＝d 前一晚 15:00 到 d 05:00。"""
    rows = []
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return rows
    for r in reader:
        if len(r) < 18:
            continue
        contract = r[2].strip()
        if not (len(contract) == 6 and contract.isdigit()):
            continue
        try:
            day = dt.datetime.strptime(r[0].strip(), "%Y/%m/%d").date()
        except ValueError:
            continue
        rows.append({"date": day, "contract": contract, "session": r[17].strip(),
                     "open": _num(r[3]), "close": _num(r[6]), "settle": _num(r[10]),
                     "volume": _num(r[9]) or 0.0})
    return rows


def tx_measures(rows, day, prev):
    """回 (gap_tx_open, 夜盤收盤, 夜盤對前日結算的漲跌, 契約)。契約取 ``day`` 日盤成交量最大的月份；
    缺日盤時改看盤後；前一日結算價取同一契約的日盤列。任一缺值就回對應的 None。"""
    day_rows = [r for r in rows if r["date"] == day and r["session"] == "一般" and r["volume"] > 0]
    night_rows = [r for r in rows if r["date"] == day and r["session"] == "盤後" and r["volume"] > 0]
    pool = day_rows or night_rows
    if not pool:
        return None, None, None, None
    contract = max(pool, key=lambda r: r["volume"])["contract"]
    settle = next((r["settle"] for r in rows if r["date"] == prev and r["contract"] == contract
                   and r["session"] == "一般"), None)
    day_open = next((r["open"] for r in day_rows if r["contract"] == contract), None)
    night_close = next((r["close"] for r in night_rows if r["contract"] == contract), None)
    gap = day_open / settle - 1 if day_open and settle else None
    night_chg = night_close / settle - 1 if night_close and settle else None
    return gap, night_close, night_chg, contract


# ---------- 純函式：判定 ----------

def regime_by_close(breadth, vix):
    """只用 breadth 與 VIX 能判到的 regime；資料缺就回 None。順序就是 skill 的優先序：VIX>30 先判宣洩。"""
    if breadth is None or vix is None:
        return None
    if vix > 30:
        return "capitulation"
    if breadth < 0.25:
        return "broad_selloff"
    if breadth > 0.50 and vix < 20:
        return "tailwind"
    return "rotation"


def action_flag(action, day_return):
    if day_return is None:
        return None
    if action in ("wait", "hold") and abs(day_return) >= BIG_MOVE:
        return "idle_on_big_move_up" if day_return > 0 else "idle_on_big_move_down"
    if action == "buy" and day_return <= -BIG_MOVE:
        return "buy_on_big_drop"
    if action == "reduce" and day_return >= BIG_MOVE:
        return "reduce_on_big_rally"
    return None


def _sign(x):
    return 0 if x is None or x == 0 else (1 if x > 0 else -1)


def _prob(x):
    """機率欄位必須是 [0, 1] 的小數；其他（缺、字串、百分數 62）一律當缺，由呼叫端記 note。"""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or math.isnan(x):
        return None
    return float(x) if 0 <= x <= 1 else None


def _up(x):
    """大於 0 → 1、否則 0；缺值回 None。"""
    return None if x is None else int(x > 0)


def build_outcome(call, *, prev, prev_close, open_, close, idx_0905, tx, breadth, vix, now=None,
                  baselines=None):
    """一筆判讀 → outcome 列（純函式）。``tx`` 是 `tx_measures` 的回傳值；``baselines`` 是
    `baseline_fields` 的回傳（缺就不寫基準欄）。"""
    day = call["date"]
    exp = call.get("gap_expected")
    gap_tx, night_close, night_chg, contract = tx
    actual = {
        "gap_open_official": open_ / prev_close - 1 if open_ and prev_close else None,
        "gap_0905": idx_0905 / prev_close - 1 if idx_0905 and prev_close else None,
        "gap_tx_open": gap_tx,
    }
    night_spot = night_close / prev_close - 1 if night_close and prev_close else None
    day_ret = close / prev_close - 1 if close and prev_close else None
    regime = call.get("regime")
    derived = regime_by_close(breadth, vix)
    excl = call.get("exclude_from_scoring")
    row = {
        "date": day, "prev_session": prev.isoformat(),
        "scorable": excl is False,
        "exclude_from_scoring": excl,
        "gap_expected": exp,
        **{k: _r(v) for k, v in actual.items()},
        **{f"err_{k}": _r(v - exp) if v is not None and exp is not None else None for k, v in actual.items()},
        "night_spot_gap": _r(night_spot),
        "night_tx_chg": _r(night_chg),
        "input_err": _r(exp - (night_chg if call.get("gap_basis") == "tx_settle" else night_spot))
        if exp is not None and (night_chg if call.get("gap_basis") == "tx_settle" else night_spot) is not None else None,
        "gap_basis": call.get("gap_basis"),
        "tx_contract": contract,
        "day_return": _r(day_ret),
        "intraday_return": _r(close / open_ - 1) if close and open_ else None,
        "gap_dir_hit": (_sign(exp) == _sign(actual["gap_0905"])) if exp is not None and actual["gap_0905"] is not None else None,
        "day_dir_hit": (_sign(exp) == _sign(day_ret)) if exp is not None and day_ret is not None else None,
        "breadth_ma20_close": _r(breadth, 4),
        "vix_prior": _r(vix, 2),
        "regime": regime,
        "regime_by_close": derived,
        "regime_consistent": (regime == derived) if regime in REGIMES and derived else None,
        "action": call.get("action"),
        "action_flag": action_flag(call.get("action"), day_ret),
        "computed_at": (now or dt.datetime.now()).strftime("%Y-%m-%dT%H:%M+08:00"),
    }
    ys = {"close_up": _up(day_ret), "oc_up": _up(close / open_ - 1) if close and open_ else None,
          "gap_up": _up(actual["gap_0905"])}
    bad = []
    for t in PROB_TARGETS:
        raw = call.get(f"p_{t}")
        p = _prob(raw)
        if raw is not None and p is None:
            bad.append(f"p_{t}={raw!r}")
        row[f"p_{t}"] = p
        row[f"y_{t}"] = ys[t]
    row["model_version"] = call.get("model_version")
    row["skill_version"] = call.get("skill_version")
    row["night_dir_up"] = _up(night_spot)
    if baselines:
        row.update(baselines)
    # (d) 方向值＝夜盤符號；機率欄先留 null（夜盤歷史回補前估不出）
    for t in PROB_TARGETS:
        row[f"base_d_dir_{t}"] = row["night_dir_up"]
        row.setdefault(f"base_d_p_{t}", None)
    if regime not in REGIMES:
        row["note"] = f"自創標籤 {regime!r} 無定義可驗"
    elif excl is None:
        row["note"] = "exclude_from_scoring 未標記，不計分"
    if bad:
        row["note"] = "；".join(x for x in (row.get("note"), "機率欄不合法（要 0~1 小數）已當缺：" + "、".join(bad)) if x)
    return row


def _r(x, nd=5):
    return None if x is None else round(float(x), nd)


# ---------- 純函式：彙總 ----------

def _boot(values, stat, n=2000, seed=42):
    """iid bootstrap 95% 區間。重抽裡算不出統計量的比例超過 ``MAX_UNDEFINED`` 就回 None：
    默默丟掉那些重抽，剩下的會只由少數有資訊的樣本決定，區間窄得假。"""
    import numpy as np
    arr = np.asarray(values)
    if len(arr) < 2:
        return None
    rng = np.random.default_rng(seed)
    raw = [stat(arr[rng.integers(0, len(arr), len(arr))]) for _ in range(n)]
    stats = [s for s in raw if s is not None and not math.isnan(s)]
    if not stats or (n - len(stats)) / n > MAX_UNDEFINED:
        return None
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return float(lo), float(hi)


def _slope(pairs):
    """過原點迴歸斜率：實際 ≈ 斜率 × 預估。pairs 是 (預估, 實際) 的 2 欄陣列。"""
    sxx = float((pairs[:, 0] ** 2).sum())
    return float((pairs[:, 0] * pairs[:, 1]).sum()) / sxx if sxx > 0 else float("nan")


def summarize(rows, measure, n_boot=2000, seed=42, raw_key="night_spot_gap"):
    """誤差、偏差、方向命中對 ``gap_expected``（實際寫下的預估）算；縮放比對 ``night_spot_gap``
    （夜盤公式的原始值）算——``gap_expected`` 可能已經乘過縮放比，拿它估縮放比會把修正再修一次。"""
    import numpy as np
    pts = [(r["gap_expected"], r[measure]) for r in rows
           if r.get("gap_expected") is not None and r.get(measure) is not None]
    n = len(pts)
    out = {"measure": measure, "n": n}
    if n == 0:
        out["verdict"] = "inconclusive（沒有樣本）"
        return out
    arr = np.asarray(pts, dtype=float)
    err = arr[:, 1] - arr[:, 0]
    out["mae"] = float(np.abs(err).mean())
    out["bias"] = float(err.mean())
    out["bias_ci"] = _boot(err, lambda a: float(a.mean()), n_boot, seed)
    raw = np.asarray([(r[raw_key], r[measure]) for r in rows
                      if r.get(raw_key) is not None and r.get(measure) is not None], dtype=float)
    raw = raw.reshape(-1, 2)
    out["n_scale"] = int((np.abs(raw[:, 0]) >= RATIO_FLOOR).sum())
    out["slope"] = _slope(raw) if len(raw) else float("nan")
    out["slope_ci"] = _boot(np.arange(len(raw)), lambda i: _slope(raw[i]), n_boot, seed) if len(raw) else None
    big = raw[np.abs(raw[:, 0]) >= RATIO_FLOOR]
    out["ratio_median"] = float(np.median(big[:, 1] / big[:, 0])) if len(big) else None
    hits = [_sign(e) == _sign(a) for e, a in pts]
    out["dir_hit"] = float(np.mean(hits))
    ci = out["bias_ci"]
    crosses = ci is None or ci[0] <= 0 <= ci[1]
    out["verdict"] = "inconclusive" if n < MIN_N or crosses else "偏差顯著"
    sci = out["slope_ci"]
    out["apply_scaling"] = bool(out["n_scale"] >= MIN_N and sci is not None and not (sci[0] <= 1 <= sci[1]))
    return out


# ---------- 純函式：基準與機率計分 ----------

def hist_targets(merged):
    """{date: (open, high, low, close)} → 逐日三個目標的實際方向（依日期排序、第一天無前收不列）。
    gap_up 沒有逐日 09:05 指數可用，官方開盤缺口不是同一個事件，所以固定 None（基準不比 gap_up）。"""
    days = sorted(merged)
    out = []
    for prev, day in zip(days, days[1:]):
        o, c, pc = merged[day][0], merged[day][3], merged[prev][3]
        out.append({"date": day, "close_up": _up(c - pc), "oc_up": _up(c - o), "gap_up": None})
    return out


def sp_directions(series):
    """[(date, close)] → [(date, 當日是否收漲)]（依日期排序；第一筆沒有前值不列）。"""
    ser = sorted(series)
    return [(d, int(v > pv)) for (_, pv), (d, v) in zip(ser, ser[1:])]


def _sp_dir_before(sp, day):
    """``day`` 之前（嚴格小於）最近一個 S&P 交易日的方向；沒有就 None。"""
    import bisect
    i = bisect.bisect_left([d for d, _ in sp], day)
    return sp[i - 1][1] if i else None


def _laplace(ups, n):
    return (ups + 1) / (n + 2)


def baseline_fields(day, hist, sp, window=ROLL_WINDOW):
    """forecast 日 ``day`` 的基準欄位：每個目標 × (a)(b)(c) 各一組方向值（`base_<k>_dir_<t>`）與機率值
    （`base_<k>_p_<t>`）。**只用 date < day 的歷史**（`hist` 的 date 是 date 物件）；歷史是空的整組回 None，
    ``sp`` 是 None（資料不可用）時 (c) 回 None。機率＝(頻率分子 + 1) / (樣本 + 2)。"""
    prior = [h for h in sorted(hist, key=lambda h: h["date"]) if h["date"] < day][-window:]
    sp_today = _sp_dir_before(sp, day) if sp else None
    out = {}
    for t in PROB_TARGETS:
        for k in "abc":
            out[f"base_{k}_dir_{t}"] = out[f"base_{k}_p_{t}"] = None
        out[f"base_n_{t}"] = 0
        if (t, "a") in NO_BASELINE:   # 只有方向可算：(a) 恆為 1、(c) 只依 S&P 前一交易日
            out[f"base_a_dir_{t}"] = 1
            if sp_today is not None:
                out[f"base_c_dir_{t}"] = sp_today
            continue
        ys = [h[t] for h in prior if h[t] is not None]
        if not ys:
            continue
        out[f"base_n_{t}"] = len(ys)
        out[f"base_a_dir_{t}"] = 1
        out[f"base_a_p_{t}"] = _r(_laplace(sum(ys), len(ys)), 6)
        yday = prior[-1][t]
        if yday is not None:
            nxt = [b[t] for a, b in zip(prior, prior[1:]) if a[t] == yday and b[t] is not None]
            out[f"base_b_dir_{t}"] = yday
            out[f"base_b_p_{t}"] = _r(_laplace(sum(nxt), len(nxt)), 6)
        if sp_today is not None:
            same = [h[t] for h in prior if h[t] is not None and _sp_dir_before(sp, h["date"]) == sp_today]
            out[f"base_c_dir_{t}"] = sp_today
            out[f"base_c_p_{t}"] = _r(_laplace(sum(same), len(same)), 6)
    return out


def _cbb_ci(values, block=BLOCK, n=2000, seed=42):
    """circular block bootstrap 的 95% 區間（對平均）；少於 2 筆回 None。values 要依時間排序。"""
    import numpy as np
    arr = np.asarray(values, dtype=float)
    size = len(arr)
    if size < 2:
        return None
    block = min(block, size)
    nb = -(-size // block)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, size, (n, nb))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % size).reshape(n, -1)[:, :size]
    lo, hi = np.percentile(arr[idx].mean(axis=1), [2.5, 97.5])
    return float(lo), float(hi)


def _verdict(n, ci):
    if n < MIN_N or ci is None or ci[0] <= 0 <= ci[1]:
        return "inconclusive"
    return "模型優於基準" if ci[0] > 0 else "模型劣於基準"


def prob_summary(rows, target, n_boot=2000, seed=42):
    """單一目標的機率計分。缺 `p_<target>`／`y_<target>` 的列（舊列）跳過、計入 ``n_skipped``。
    d_i＝基準 Brier − 模型 Brier（正＝模型較好）；a_i＝模型命中 − 基準命中（模型方向＝p>0.5）。"""
    import numpy as np
    rows = sorted(rows, key=lambda r: r["date"])
    elig = [r for r in rows if r.get(f"p_{target}") is not None and r.get(f"y_{target}") is not None]
    out = {"target": target, "n": len(elig), "n_skipped": len(rows) - len(elig), "baselines": {}}
    if not elig:
        return out
    p = np.asarray([r[f"p_{target}"] for r in elig], dtype=float)
    y = np.asarray([r[f"y_{target}"] for r in elig], dtype=float)
    out.update(p_bar=float(p.mean()), y_bar=float(y.mean()), bias=float(p.mean() - y.mean()),
               brier=float(((p - y) ** 2).mean()))
    hit_m = ((p > 0.5).astype(float) == y).astype(float)
    for k in BASELINES:
        na = (target, k) in NO_BASELINE   # 機率不可用：舊列即使有值也不採用
        nd = (target, k) in NO_DIR        # 方向不可用
        bp = [] if na else [(i, r[f"base_{k}_p_{target}"]) for i, r in enumerate(elig)
                            if r.get(f"base_{k}_p_{target}") is not None]
        bd = [] if nd else [(i, r[f"base_{k}_dir_{target}"]) for i, r in enumerate(elig)
                            if r.get(f"base_{k}_dir_{target}") is not None]
        b = {"n_brier": len(bp), "n_hit": len(bd), "brier": None, "d_mean": None, "d_ci": None,
             "a_mean": None, "a_ci": None}
        if bp:
            ii = np.asarray([i for i, _ in bp])
            base_brier = (np.asarray([v for _, v in bp], dtype=float) - y[ii]) ** 2
            d = base_brier - (p[ii] - y[ii]) ** 2
            b.update(brier=float(base_brier.mean()), d_mean=float(d.mean()), d_ci=_cbb_ci(d, BLOCK, n_boot, seed))
        if bd:
            ii = np.asarray([i for i, _ in bd])
            hit_b = (np.asarray([v for _, v in bd], dtype=float) == y[ii]).astype(float)
            a = hit_m[ii] - hit_b
            b.update(a_mean=float(a.mean()), a_ci=_cbb_ci(a, BLOCK, n_boot, seed))
        b["verdict"] = _verdict(len(bp), b["d_ci"]) if bp else "inconclusive（無機率基準）"
        out["baselines"][k] = b
    return out


def regime_summary(rows):
    checked = [r for r in rows if r.get("regime_consistent") is not None]
    return {"n": len(checked), "consistent": sum(1 for r in checked if r["regime_consistent"]),
            "unscorable_labels": sum(1 for r in rows if r.get("regime") not in REGIMES)}


# ---------- 輸出 ----------

def _pct(x, signed=True):
    return "—" if x is None else (f"{x * 100:+.2f}%" if signed else f"{x * 100:.1f}%")


def _ci(ci, scale=100, fmt="{:+.2f}"):
    return "—" if not ci else f"[{fmt.format(ci[0] * scale)}, {fmt.format(ci[1] * scale)}]"


def render_rows(rows, out=print):
    out("日期        regime        動作   預估缺口  官方開盤  09:05    台指期開盤 夜盤×現貨 輸入誤差  全日     breadth VIX   標籤")
    for r in rows:
        mark = "" if r["scorable"] else " (不計分)"
        cons = {True: "符合", False: f"不符→{r['regime_by_close']}", None: "—"}[r.get("regime_consistent")]
        out(f"{r['date']}  {str(r['regime']):13s} {str(r['action']):6s} {_pct(r['gap_expected']):>8s}  "
            f"{_pct(r['gap_open_official']):>8s}  {_pct(r['gap_0905']):>8s}  {_pct(r['gap_tx_open']):>8s}  "
            f"{_pct(r['night_spot_gap']):>8s}  {_pct(r['input_err']):>8s}  {_pct(r['day_return']):>7s}  "
            f"{_pct(r['breadth_ma20_close'], False):>6s} {r['vix_prior'] if r['vix_prior'] is not None else '—':>5} "
            f"{cons}{mark}{'  ⚑' + r['action_flag'] if r.get('action_flag') else ''}")


def render_prob_summary(rows, out=print):
    out("機率計分（Brier 越小越好；d＝基準−模型，正＝模型較好；10 日 block bootstrap 95% CI）：")
    for t in PROB_TARGETS:
        ps = prob_summary(rows, t)
        head = f"  {TARGET_LABEL[t]:10s}"
        if not ps["n"]:
            out(f"{head} 沒有帶 p_{t} 的可計分列（舊列跳過 {ps['n_skipped']} 筆）")
            continue
        base = (f"{head} n={ps['n']}（跳過無 p 的舊列 {ps['n_skipped']}） p̄ {ps['p_bar']:.3f} − ȳ {ps['y_bar']:.3f} "
                f"= 整體偏差 {ps['bias']:+.3f}")
        if ps["n"] < MIN_N:
            out(f"{base}；n<{MIN_N} 只報整體偏差 → inconclusive")
            continue
        out(f"{base}；模型 Brier {ps['brier']:.4f}")
        for k in BASELINES:
            b = ps["baselines"][k]
            if b["n_brier"]:
                d = f"基準 Brier {b['brier']:.4f} d̄ {b['d_mean']:+.4f} {_ci(b['d_ci'], 1, '{:+.4f}')}（n={b['n_brier']}）"
            elif (t, k) in NO_BASELINE:
                d = "Brier 不可用（缺 09:05 歷史）"
            else:
                d = "Brier 不可用（無機率基準）"
            a = "命中差不可用" if b["a_mean"] is None else (
                f"命中差 ā {b['a_mean']:+.3f} {_ci(b['a_ci'], 1, '{:+.3f}')}（n={b['n_hit']}）")
            out(f"    vs ({k}) {BASELINE_LABEL[k]}：{d}；{a} → {b['verdict']}")


def gap_groups(rows):
    """[(標籤, 縮放比的 raw 欄, 該口徑的列)]：依 gap_basis 分組，render_summary／brief／bark_line 共用。"""
    return [("夜盤÷前日現貨收盤（舊口徑）", "night_spot_gap", [r for r in rows if r.get("gap_basis") != "tx_settle"]),
            ("夜盤÷同合約前日結算（新口徑）", "night_tx_chg", [r for r in rows if r.get("gap_basis") == "tx_settle"])]


def render_summary(rows, out=print, label="可計分"):
    out(f"\n── 彙總（{label} {len(rows)} 筆；誤差＝實際 − 預估）──")
    groups = gap_groups(rows)
    for glabel, raw_key, grows in groups:
        if not grows:
            continue
        out(f"[缺口口徑：{glabel}，{len(grows)} 筆；兩種口徑不混算]")
        for m in MEASURES:
            s = summarize(grows, m, raw_key=raw_key)
            if not s["n"]:
                out(f"{MEASURE_LABEL[m]:8s} 沒有樣本")
                continue
            ratio = "—" if s["ratio_median"] is None else f"{s['ratio_median']:.2f}"
            out(f"{MEASURE_LABEL[m]:8s} n={s['n']:<3d} MAE {s['mae'] * 100:.2f}pp  偏差 {s['bias'] * 100:+.2f}pp "
                f"{_ci(s['bias_ci'])}  縮放比(實際÷夜盤公式，n={s['n_scale']}) {s['slope']:.2f} {_ci(s['slope_ci'], 1, '{:.2f}')}  "
                f"比值中位 {ratio}  方向命中 {s['dir_hit'] * 100:.0f}%  → {s['verdict']}"
                f"{'' if s['apply_scaling'] else '，縮放比不套用'}")
    day = [r["day_dir_hit"] for r in rows if r.get("day_dir_hit") is not None]
    if day:
        out(f"缺口方向 vs 全日方向：{sum(day)}/{len(day)} 同向（描述性，盤前判讀不預測收盤）")
    rs = regime_summary(rows)
    out(f"regime（只驗 breadth＋VIX）：{rs['consistent']}/{rs['n']} 符合；自創標籤無法計分 {rs['unscorable_labels']} 筆")
    flags = [f"{r['date']} {r['action']}→{r['action_flag']}" for r in rows if r.get("action_flag")]
    out("動作事後描述（不是績效）：" + ("；".join(flags) if flags else "沒有大漲大跌日的觀望／逆向動作"))
    render_prob_summary(rows, out)
    if len(rows) < MIN_N:
        out(f"⚠ 樣本 {len(rows)} 筆 < {MIN_N}：所有結論 inconclusive，不能聲稱判讀有經驗證的優勢。")


def bark_line(rows, new_rows):
    """給 18:00 推播的一段文字：今天新增的結果＋累計偏差。"""
    parts = []
    for r in new_rows:
        parts.append(f"{r['date']} 預估 {_pct(r['gap_expected'])}，實際 09:05 {_pct(r['gap_0905'])}"
                     f"／期貨 {_pct(r['gap_tx_open'])}，全日 {_pct(r['day_return'])}；"
                     f"regime {r['regime']}{'（符合）' if r.get('regime_consistent') else '（不符或無法驗）'}")
    for glabel, raw_key, grows in gap_groups([r for r in rows if r["scorable"]]):
        s = summarize(grows, "gap_0905", raw_key=raw_key)
        if not s["n"]:
            continue
        if raw_key == "night_tx_chg":
            parts.append(f"累計（{glabel}）n={s['n']} 偏差 {s['bias'] * 100:+.2f}pp、縮放比 {s['slope']:.2f}，{s['verdict']}")
        else:
            parts.append(f"累計（{glabel}）n={s['n']} 偏差 {s['bias'] * 100:+.2f}pp，{s['verdict']}（舊口徑不給縮放比）")
    return "\n".join(parts)


# ---------- I/O ----------

def read_outcomes(path=OUTCOMES):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line and not line.startswith("#"):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{ln} 不是合法 JSON: {exc}")
    return rows


def append_outcomes(path, rows):
    """只追加檔案裡還沒有的 date（同一批裡重複的也只留第一筆）；回傳實際寫入的列。

    讀檔、比對、寫入在同一把 flock 底下做，兩個行程同時 --append 也不會寫出重複日期。"""
    import fcntl
    path = Path(path)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            have = {r["date"] for r in read_outcomes(path)}
            new = []
            for r in rows:
                if r["date"] not in have:
                    have.add(r["date"])
                    new.append(r)
            for r in new:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return new


def load_calls(path=CALLS):
    """讀判讀檔，休市日照 `verify_swing_decisions.read_log` 的聯集規則排除（不另寫一份）。"""
    from verify_swing_decisions import read_log
    df = read_log(path)
    calls = json.loads(df.to_json(orient="records", force_ascii=False)) if len(df) else []
    return calls, df.attrs.get("closed_excluded", 0)


class Fetcher:
    """官方端點的抓取＋快取。失敗回 None 並記原因，不丟例外。"""

    def __init__(self):
        from market_data import tw_official_http as http
        self.http = http
        self.hist, self.tx_cache, self.notes = {}, {}, []

    def month(self, day):
        key = (day.year, day.month)
        if key not in self.hist:
            resp, reason = self.http.get(HIST_URL, params={"date": f"{day:%Y%m}01", "response": "json"},
                                         expect="json")
            self.hist[key] = parse_hist(resp.json()) if reason is None else {}
            if reason:
                self.notes.append(f"MI_5MINS_HIST {day:%Y-%m}：{reason}")
        return self.hist[key]

    def session(self, day):
        """回 (前一交易日, 前收, 當日開, 當日收)；當日還沒有收盤資料回 None。"""
        cur = self.month(day)
        if day not in cur:
            return None
        prev_month = (day.replace(day=1) - dt.timedelta(days=1))
        days = sorted({**self.month(prev_month), **cur})
        i = days.index(day)
        if i == 0:
            return None
        prev = days[i - 1]
        merged = {**self.month(prev_month), **cur}
        return prev, merged[prev][3], merged[day][0], merged[day][3]

    def history(self, day):
        """``day`` 之前約 252 個交易日的逐日目標方向（`hist_targets`）；任何一個月抓不到（含 stat 非 OK）就回 None 並記進 ``notes``（輸出會印），不會被當成 0。"""
        merged, cur, gaps = {}, day.replace(day=1), []
        for _ in range(HIST_MONTHS):
            m = self.month(cur)
            if not m:   # 往回抓的都是已收盤月份，必有交易日：空代表抓取失敗（含 stat 非 OK），不能跨缺口併成相鄰日
                gaps.append(f"{cur:%Y-%m}")
            merged.update(m)
            cur = cur.replace(day=1) - dt.timedelta(days=1)
        if gaps:
            self.notes.append(f"MI_5MINS_HIST 缺 {'、'.join(gaps)}：基準歷史不完整，整組不用")
            return None
        return hist_targets(merged)

    def index_0905(self, day):
        resp, reason = self.http.get(INDEX_URL, params={"response": "json", "date": f"{day:%Y%m%d}"},
                                     expect="json")
        if reason:
            self.notes.append(f"MI_5MINS_INDEX {day}：{reason}")
            return None
        val = parse_index_at(resp.json(), day)
        if val is None:
            self.notes.append(f"MI_5MINS_INDEX {day}：回應日期不符或缺 09:05:00")
        return val

    def tx(self, day, prev):
        from market_data import taifex
        key = (prev, day)
        if key not in self.tx_cache:
            text, reason = taifex.fetch_csv(TX_URL, {"down_type": "1", "commodity_id": "TX",
                                                     "queryStartDate": f"{prev:%Y/%m/%d}",
                                                     "queryEndDate": f"{day:%Y/%m/%d}"})
            if reason:
                self.notes.append(f"futDataDown {prev}~{day}：{reason}")
            self.tx_cache[key] = parse_tx(text) if text else []
        return tx_measures(self.tx_cache[key], day, prev)


def breadth_at(engine, day):
    """收盤 breadth（站上 MA20 比例），與 `screen_tw` 報告 §1 同一個定義、同一份程式碼。"""
    import pandas as pd
    import screen_tw
    as_of, px, inst, mgn, val, rev, info, idx = screen_tw.load(engine, pd.Timestamp(day))
    if as_of.date() != day:
        return None
    df, _ = screen_tw.build(as_of, px, inst, mgn, val, rev, info, idx, 0)
    ind = df[~df["is_etf"]]
    return float((ind["close"] > ind["ma20"]).mean()) if len(ind) else None


def vix_prior(engine, day):
    from sqlalchemy import text
    with engine.connect() as conn:
        return conn.execute(text("select value from market.macro_series where series_id='^VIX' "
                                 "and date < :d order by date desc limit 1"), {"d": day}).scalar()


def sp_series(engine):
    """^GSPC 日收盤 [(date, close)]（date 是美股交易日）。"""
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text("select date, value from market.macro_series where series_id='^GSPC' "
                                 "and value is not null order by date")).fetchall()
    return [(r[0], float(r[1])) for r in rows]


def compute(calls, *, skip_dates=(), fetcher=None, engine=None, today=None, out=print):
    """對每筆還沒算過、當日已收盤的判讀算 outcome。"""
    today = today or dt.date.today()
    todo = [c for c in calls if c["date"] not in set(skip_dates)
            and dt.date.fromisoformat(c["date"]) <= today]
    if not todo:
        return []
    fetcher = fetcher or Fetcher()
    if engine is None:
        from market_data.db import get_engine
        engine = get_engine()
    try:
        sp = sp_directions(sp_series(engine))
        if not sp:
            raise ValueError("market.macro_series 沒有 ^GSPC 資料")
    except Exception as exc:  # noqa: BLE001  資料源失敗要明講不可用，(c) 基準留 null，不當 0
        out(f"  ⚠ S&P 基準不可用（{type(exc).__name__}: {exc}）：基準 (c) 留空")
        sp = None
    rows = []
    for c in todo:
        day = dt.date.fromisoformat(c["date"])
        sess = fetcher.session(day)
        if sess is None:
            out(f"  {c['date']}：官方日資料還沒有這天（未收盤或抓取失敗），跳過")
            continue
        prev, prev_close, open_, close = sess
        breadth = breadth_at(engine, day)
        if breadth is None:
            out(f"  {c['date']}：DB 還沒有這天的收盤行情，跳過")
            continue
        vix = vix_prior(engine, day)
        hist = fetcher.history(day)
        if not hist:
            out(f"  ⚠ {c['date']}：基準歷史不可用（官方日資料缺月或抓不到），基準 (a)(b)(c) 留空")
        baselines = baseline_fields(day, hist, sp) if hist else None
        row = build_outcome(c, prev=prev, prev_close=prev_close, open_=open_, close=close,
                            idx_0905=fetcher.index_0905(day), tx=fetcher.tx(day, prev),
                            breadth=breadth, vix=None if vix is None else float(vix), baselines=baselines)
        missing = [k for k in ("gap_0905", "gap_tx_open", "night_spot_gap") if row[k] is None]
        if missing and (today - day).days <= DEFER_DAYS:
            # outcome 一寫就不再重算：來源暫時失敗時先不寫，下一輪再抓
            out(f"  {c['date']}：{'、'.join(missing)} 暫時取不到，延後寫入（{DEFER_DAYS} 天內每輪重試）")
            continue
        if missing:
            row["note"] = "；".join(x for x in (row.get("note"), f"超過 {DEFER_DAYS} 天仍缺 {'、'.join(missing)}") if x)
        rows.append(row)
    for n in fetcher.notes:
        out(f"  ⚠ {n}")
    return rows


def brief(path=OUTCOMES, last=5, out=print):
    rows = read_outcomes(path)
    if not rows:
        out("還沒有回驗結果（18:00 排程寫 journal/morning-calls-outcomes.jsonl）")
        return
    render_rows(rows[-last:], out)
    render_summary([r for r in rows if r["scorable"]], out)
    # 縮放建議只看新口徑（tx_settle）：skill 把比例乘在「夜盤收盤÷結算價」上，舊口徑的比例不能頂替
    new = gap_groups([r for r in rows if r["scorable"]])[1]
    s = summarize(new[2], "gap_0905", raw_key=new[1])
    if not s.get("apply_scaling"):
        out(f"→ 今天算開盤缺口時：新口徑樣本 n={s.get('n_scale', 0)}（需 ≥{MIN_N} 且區間不含 1），"
            "inconclusive，縮放比只當提醒，不要拿來修正預估，也不要拿舊口徑的比例頂替。")
    else:
        out(f"→ 縮放比 {s['slope']:.2f} 已有統計支持（n≥{MIN_N}、區間不含 1）：把**夜盤公式算出的原始缺口**乘上它再寫進 gap_expected，並在 reason 註明（不要乘在已修正過的數字上）。")


def main(argv=None):
    ap = argparse.ArgumentParser(description="回驗 morning-calls.jsonl 的盤前判讀（缺口、regime、動作）")
    ap.add_argument("--calls", default=str(CALLS))
    ap.add_argument("--outcomes", default=str(OUTCOMES))
    ap.add_argument("--append", action="store_true", help="把新算出的結果追加進 outcomes 檔（同一天不重寫）")
    ap.add_argument("--brief", action="store_true", help="只讀 outcomes 檔印近期校正（不連網、不碰 DB）")
    ap.add_argument("--all", action="store_true", help="彙總也納入不計分的列（描述用）")
    ap.add_argument("--bark", action="store_true", help="--append 後最後印一段推播文字（以 BARK: 開頭）")
    ap.add_argument("--last", type=int, default=5, help="--brief 列出最近幾筆（預設 5）")
    a = ap.parse_args(argv)

    if a.brief:
        brief(a.outcomes, a.last)
        return 0
    calls, closed = load_calls(a.calls)
    print(f"判讀 {len(calls)} 筆（已排除休市日 {closed} 筆）")
    existing = read_outcomes(a.outcomes)
    skip = {r["date"] for r in existing} if a.append else set()
    rows = compute(calls, skip_dates=skip)
    new = append_outcomes(a.outcomes, rows) if a.append else []
    shown = (existing + new) if a.append else rows
    shown = sorted(shown, key=lambda r: r["date"])
    if shown:
        render_rows(shown)
        render_summary([r for r in shown if r["scorable"]])
        if a.all:
            render_summary(shown, label="全部（含不計分）")
    if a.append:
        print(f"\n寫入 {len(new)} 筆到 {a.outcomes}")
        if a.bark and new:
            print("BARK: " + bark_line(shown, new).replace("\n", " ｜ "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
