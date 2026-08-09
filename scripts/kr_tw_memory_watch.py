#!/usr/bin/env python
"""盤中監看台韓記憶體同日背離，只在門檻觸發時推 Bark。

skill `tw-morning-call` Step 2 有一格是人工的：韓股與台股**同時段**（韓 09:00-15:30 KST
＝台 08:00-14:30），`scripts/overnight.py` 只給到韓股前一交易日收盤。台灣記憶體對韓國記憶體
同日 r=0.577、對費半只有 0.123（739 交易日實測，見 docs/tw-swing-pipeline.md 族群代理節），
所以韓國開盤後的方向是記憶體標的當日的第一順位輸入，而它必須盤中才拿得到。這支就補那一格。

    doppler run -p shioaji -c dev -- uv run --env-file .env python scripts/kr_tw_memory_watch.py
    ... scripts/kr_tw_memory_watch.py --once            # 立刻採樣一次就結束（測連線用）
    ... scripts/kr_tw_memory_watch.py --selftest        # 只驗警報門檻邏輯，不連外

**yfinance 的韓股日 K 不可信，`previousClose` 也不可信。** 2026-08-04 實測：000660.KS 的日 K
最後一根停在 07-31、08-03 整根不見，而 `previousClose` 也跟著停在 07-31 的 1,718,000——
拿它算漲跌會得到 -8.79%，那是**昨天**的跌幅。只有 `fast_info['lastPrice']` 是對的。
所以 baseline 一律在**韓股開盤前**用 lastPrice 鎖住（此時它就是前一交易日收盤），
開盤後才啟動會拿到當日盤中值當 baseline ⇒ 那時本腳本直接拒跑。

台股基準用 `market.price` 的前一交易日**未還原**收盤——這裡要的是「當日漲跌幅」，
跟看板同口徑，不套還原因子（還原價是算報酬時才要，見 market_data/AGENTS.md）。

缺 Shioaji 金鑰時會靜默降級成延遲報價，本腳本改為直接失敗。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_provider.shioaji_fetcher import _ensure_session  # noqa: E402
from market_data.db import get_engine  # noqa: E402
from scripts.intraday_breadth import load_panel, snap  # noqa: E402

KR = {"000660.KS": "SK海力士", "005930.KS": "三星電子", "^KS11": "KOSPI"}
KR_MEM = ["000660.KS", "005930.KS"]          # 韓國記憶體籃子（等權），KOSPI 只當大盤參考
TW_MEM = ["2344", "2408", "2337", "3006"]    # 華邦電／南亞科／旺宏／晶豪科
TW_EXTRA = ["0050"]
KR_OPEN = dtime(8, 0)                        # 台北時間；韓股 09:00 KST


def band(pct_pts: float, step: float) -> int:
    """|x| 落在第幾個 step 級距。0 = 未達門檻。用來讓同一件事只推一次。"""
    return int(abs(pct_pts) / step)


def alerts(sample: dict, peak: dict) -> list[str]:
    """回傳這次要推播的訊息；就地更新 peak（已推過的級距），所以同一級距不重推。

    三組門檻，各自獨立升級：韓國個股 3pp、KOSPI 2pp、台韓同日價差 3pp。
    """
    out = []
    for tk, step, label in (
        ("000660.KS", 3.0, KR["000660.KS"]),
        ("005930.KS", 3.0, KR["005930.KS"]),
        ("^KS11", 2.0, "KOSPI"),
    ):
        v = sample["kr"].get(tk)
        if v is None:
            continue
        b = band(v, step)
        if b > peak.get(tk, 0):
            peak[tk] = b
            out.append(f"{label} {v:+.2f}%")
    sp = sample.get("spread_pp")
    if sp is not None:
        b = band(sp, 3.0)
        if b > peak.get("spread", 0):
            peak["spread"] = b
            way = "背離收斂（台弱於韓）" if sp < 0 else "背離擴大（台強於韓）"
            out.append(f"{way} {sp:+.1f}pp　台記憶體 {sample['tw_mem']:+.2f}% / 韓記憶體 {sample['kr_mem']:+.2f}%")
    return out


def push(body: str, title: str) -> bool:
    """推 Bark。URL 從環境變數來（Doppler 注入），不落地。"""
    url = os.environ.get("BARK_URL") or os.environ.get("CUSTOM_WEBHOOK_URLS", "").split(",")[0]
    if not url.strip():
        print("  [bark] 未注入 BARK_URL／CUSTOM_WEBHOOK_URLS，略過推播", flush=True)
        return False
    try:
        r = requests.post(
            url.strip(), json={"title": title, "body": body, "group": "kr-tw-mem"}, timeout=10
        )
        return r.ok
    except requests.RequestException as e:
        print(f"  [bark] 推播失敗 {e}", flush=True)
        return False


def kr_last(tickers):
    """{ticker: lastPrice}。yfinance 的日 K／previousClose 對韓股不可信，只取 lastPrice。"""
    import yfinance as yf

    out = {}
    for tk in tickers:
        try:
            out[tk] = float(yf.Ticker(tk).fast_info["lastPrice"])
        except (KeyError, TypeError, ValueError, OSError) as e:
            print(f"  [yf] {tk} 取價失敗 {e}", flush=True)
    return out


def sample_once(api, kr_base, tw_prev, tw_codes):
    """採樣一次，回傳一筆可直接寫 JSONL 的 dict。"""
    kr_px = kr_last(list(KR))
    kr = {tk: (kr_px[tk] / kr_base[tk] - 1) * 100 for tk in kr_px if kr_base.get(tk)}
    live = snap(api, tw_codes)
    tw = {c: (live[c][0] / float(tw_prev[c]) - 1) * 100 for c in live if tw_prev.get(c)}

    def mean(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    kr_mem = mean([kr.get(t) for t in KR_MEM])
    tw_mem = mean([tw.get(t) for t in TW_MEM])
    return {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kr": {k: round(v, 2) for k, v in kr.items()},
        "kr_px": kr_px,
        "tw": {k: round(v, 2) for k, v in tw.items()},
        "tw_locked": sorted(c for c in live if live[c][1]),
        "kr_mem": round(kr_mem, 2) if kr_mem is not None else None,
        "tw_mem": round(tw_mem, 2) if tw_mem is not None else None,
        "spread_pp": round(tw_mem - kr_mem, 2) if None not in (kr_mem, tw_mem) else None,
    }


def selftest():
    peak = {}
    s = {"kr": {"000660.KS": 1.0, "005930.KS": 0.5, "^KS11": 0.4}, "spread_pp": 1.0,
         "tw_mem": 1.0, "kr_mem": 0.0}
    assert alerts(s, peak) == [], "都未達門檻時不該推"
    s["kr"]["000660.KS"] = 3.4
    assert len(alerts(s, peak)) == 1, "SK 破 3% 要推一次"
    s["kr"]["000660.KS"] = 4.9
    assert alerts(s, peak) == [], "同一級距內不重推"
    s["kr"]["000660.KS"] = 6.1
    assert len(alerts(s, peak)) == 1, "升到第二級距要再推"
    s["kr"]["000660.KS"] = 0.2
    assert alerts(s, peak) == [], "回落不推（peak 只升不降）"
    p2 = {}
    assert "收斂" in alerts({"kr": {}, "spread_pp": -3.5, "tw_mem": -2.0, "kr_mem": 1.5}, p2)[0]
    assert "擴大" in alerts({"kr": {}, "spread_pp": 9.0, "tw_mem": 5.0, "kr_mem": -4.0}, {})[0]
    assert band(-19.0, 3.0) == 6 and band(2.9, 3.0) == 0
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", default="08:30", help="開始採樣時間（台北，HH:MM），預設 08:30")
    ap.add_argument("--until", default="13:35", help="停止時間（台北，HH:MM），預設 13:35")
    ap.add_argument("--interval", type=int, default=15, help="採樣間隔（分鐘），預設 15")
    ap.add_argument("--once", action="store_true", help="立刻採樣一次就結束，不等 --start")
    ap.add_argument("--selftest", action="store_true", help="只驗警報門檻邏輯，不連外")
    ap.add_argument("--log", help="JSONL 輸出路徑，預設 logs/kr-tw-mem-<今天>.jsonl")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    now = datetime.now()
    log = Path(a.log) if a.log else Path("logs") / f"kr-tw-mem-{now:%Y-%m-%d}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)

    # baseline 必須在韓股開盤前鎖住，否則 lastPrice 已是當日盤中值。
    if now.time() >= KR_OPEN and not a.once:
        sys.exit(f"現在 {now:%H:%M} 已過韓股開盤 {KR_OPEN:%H:%M}，"
                 f"lastPrice 已是當日盤中值、無法當 baseline；請改在開盤前啟動")
    kr_base = kr_last(list(KR))
    if len(kr_base) < len(KR):
        sys.exit("韓股 baseline 不完整，中止（寧可不跑也不要拿錯基準算漲跌）")

    engine = get_engine()
    tw_codes = TW_MEM + TW_EXTRA
    _, tw_prev, _, as_of = load_panel(engine, tw_codes)
    api = _ensure_session()
    if api is None:
        sys.exit("no Shioaji session — 檢查 Doppler 是否注入 SHIOAJI_API_KEY／SHIOAJI_SECRET_KEY")

    head = {"ts": now.astimezone().isoformat(timespec="seconds"), "event": "baseline",
            "kr_base": kr_base, "tw_prev": {c: float(tw_prev[c]) for c in tw_codes if tw_prev.get(c)},
            "tw_db_as_of": f"{as_of:%Y-%m-%d}", "interval_min": a.interval,
            "window": [a.start, a.until]}
    with log.open("a") as f:
        f.write(json.dumps(head, ensure_ascii=False) + "\n")
    print(f"baseline 已鎖（{now:%H:%M}，韓股未開盤）　台股 DB 基準日 {as_of:%Y-%m-%d}　log {log}")
    for tk, nm in KR.items():
        print(f"  {nm:8}{kr_base[tk]:>14,.0f}")

    stop = datetime.combine(now.date(), dtime.fromisoformat(a.until))
    if not a.once:
        begin = datetime.combine(now.date(), dtime.fromisoformat(a.start))
        wait = (begin - datetime.now()).total_seconds()
        if wait > 0:
            print(f"等到 {a.start} 開始採樣（{wait / 60:.0f} 分鐘後）", flush=True)
            time.sleep(wait)

    peak, n = {}, 0
    while True:
        s = sample_once(api, kr_base, tw_prev, tw_codes)
        with log.open("a") as f:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
        n += 1
        print(f"{s['ts'][11:16]}  韓記憶體 {s['kr_mem']:+.2f}%　台記憶體 {s['tw_mem']:+.2f}%　"
              f"價差 {s['spread_pp']:+.1f}pp　KOSPI {s['kr'].get('^KS11', 0):+.2f}%　"
              f"0050 {s['tw'].get('0050', 0):+.2f}%", flush=True)
        msgs = alerts(s, peak)
        if n == 1:
            msgs.insert(0, f"監看啟動　台記憶體 {s['tw_mem']:+.2f}% / 韓記憶體 {s['kr_mem']:+.2f}%"
                           f"　價差 {s['spread_pp']:+.1f}pp")
        if msgs:
            ok = push("\n".join(msgs) + f"\n（{s['ts'][11:16]}　0050 {s['tw'].get('0050', 0):+.2f}%）",
                      "台韓記憶體監看")
            print(f"  [bark] {'已推' if ok else '未送出'}：{msgs}", flush=True)
        if a.once or datetime.now() >= stop:
            break
        time.sleep(a.interval * 60)

    if not a.once:
        push(f"收盤　台記憶體 {s['tw_mem']:+.2f}% / 韓記憶體 {s['kr_mem']:+.2f}%"
             f"　價差 {s['spread_pp']:+.1f}pp\n0050 {s['tw'].get('0050', 0):+.2f}%　共 {n} 次採樣",
             "台韓記憶體監看收尾")
    print(f"done　{n} 次採樣　log {log}")


if __name__ == "__main__":
    main()
