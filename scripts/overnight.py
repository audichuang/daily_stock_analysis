#!/usr/bin/env python3
"""抓昨晚國際盤的**數字**，取代用新聞搜尋湊數字。

為什麼要這支：DB 只到台股 13:30 收盤，之後到隔日開盤約 20 小時全是盲區，而用搜尋補這一段
會拿到錯的數字——實測搜尋引擎把不同日期的收盤混在一起，「台積電 ADR -4.74%」的標題其實是
另一天，當天實際是 **-1.07%**。差 3.7pp 足以把「台積電要開 -5%」講成「開 -1%」。

所以規則是：**數字走這支腳本（有日期戳、可驗證），敘事（為什麼跌、誰在賣）才用搜尋。**

用法：
    uv run python scripts/overnight.py
    uv run python scripts/overnight.py --tw-close 2350   # 附上台積電前一日收盤，折算開盤預期
"""

import argparse
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from market_data.macro import overnight_series  # noqa: E402

# 名稱、代碼、為什麼要看它、市場組（日期一致性按組檢查）。清單只有一份，在 market_data/macro.py 的
# SERIES（同時決定每日入庫哪些序列）；這裡只取 overnight=True 的那幾列。
SERIES = overnight_series()
GROUP_LABEL = {
    "us": "美股（昨晚收盤）",
    "kr": "韓股（同時段市場，見下方說明）",
    # VIX／原油／匯率盤前就開始報價，日期正常會領先美股那組一天 ⇒ 不納入日期一致性檢查，
    # 否則每天誤報一次。舊版只排除 TWD=X，所以原油與 VIX 一路在假告警。
    "cont": "連續／盤前報價（日期可能領先美股一天）",
}
ADR_RATIO = 5          # 1 ADR = 5 股台積電普通股
SOX_ALERT = -0.02      # 費半跌逾 2% → `semi_linked` 標的優先剔除（見 skill）
VIX_PANIC = 30         # 30 以上＝系統性 risk-off；20 以下＝殺盤仍侷限在族群


def adr_implied(adr_px, fx, ratio=ADR_RATIO):
    """ADR 報價折算成台股每股價格：**× 匯率 ÷ 每單位股數**。

    這個公式我在同一個 session 裡寫反過一次（`÷ 匯率`），得到 61.8 元這種荒謬值。反過來寫
    不會噴錯，只會產出一個看起來像價格的數字，所以用測試釘住。
    """
    return adr_px * fx / ratio


def fetch(period="7d"):
    out = []
    for name, ticker, why, group in SERIES:
        try:
            h = yf.Ticker(ticker).history(period=period)["Close"].dropna()
            if len(h) < 2:
                out.append({"名稱": name, "代碼": ticker, "組": group, "狀態": "資料不足"})
                continue
            out.append({"名稱": name, "代碼": ticker, "組": group, "日期": h.index[-1].date(),
                        "收盤": float(h.iloc[-1]),
                        "漲跌": float(h.iloc[-1] / h.iloc[-2] - 1),
                        "近5日": float(h.iloc[-1] / h.iloc[max(0, len(h) - 6)] - 1),
                        "why": why})
        except Exception as exc:                              # noqa: BLE001
            out.append({"名稱": name, "代碼": ticker, "組": group, "狀態": f"失敗 {type(exc).__name__}"})
    return out


def date_warnings(rows):
    """日期一致性**按市場組分開檢查**，回傳警告字串列表（空＝一致）。

    不能全部混在一起比：韓股與台股同時段（韓 09:00-15:30 KST），所以盤前跑到的韓股收盤
    正常會比美股那組**晚一個日曆日**——混著比會每天誤報。反過來，同一組內日期不一致才是
    真的抓到不同場次。`cont` 組（VIX／原油／匯率）盤前就報價、日期本來就領先，不檢查。
    """
    warns = []
    for group in ("us", "kr"):
        dates = {r["日期"] for r in rows if "狀態" not in r and r["組"] == group}
        if len(dates) > 1:
            warns.append(f"**警告：{GROUP_LABEL[group]} 各序列日期不一致 {sorted(dates)}"
                         f"——可能混到不同交易日，不要直接引用**")
    return warns


def main(argv=None):
    p = argparse.ArgumentParser(description="昨晚國際盤數字（給 skill Step 0a 用）")
    p.add_argument("--tw-close", type=float, default=None,
                   help="台積電前一交易日台股收盤價，用來折算開盤預期")
    a = p.parse_args(argv)

    rows = fetch()
    bad = [r for r in rows if "狀態" in r]
    for group, label in GROUP_LABEL.items():
        group_rows = [r for r in rows if r["組"] == group]
        if not group_rows:
            continue
        print(f"\n── {label} ──")
        print(f"{'名稱':<12}{'日期':<12}{'收盤':>12}{'漲跌':>9}{'近5日':>9}")
        for r in group_rows:
            if "狀態" in r:
                print(f"{r['名稱']:<12}{r['狀態']}")
                continue
            print(f"{r['名稱']:<12}{str(r['日期']):<12}{r['收盤']:>12,.2f}"
                  f"{r['漲跌'] * 100:>8.2f}%{r['近5日'] * 100:>8.2f}%")

    d = {r["代碼"]: r for r in rows if "狀態" not in r}
    print()
    for w in date_warnings(rows):
        print(w)

    if "^SOX" in d:
        sox = d["^SOX"]["漲跌"]
        print(f"費半 {sox * 100:+.2f}%："
              + ("**跌逾 2%，`semi_linked` 標的今天優先剔除**" if sox <= SOX_ALERT
                 else "未達 -2% 的剔除門檻"))
    if any(k in d for k in ("MU", "000660.KS", "005930.KS")):
        parts = [f"{d[k]['名稱']} {d[k]['漲跌'] * 100:+.2f}%"
                 for k in ("MU", "000660.KS", "005930.KS", "^KS11") if k in d]
        print("記憶體代理：" + "、".join(parts)
              + "　← 記憶體標的看這幾檔，**不要看費半**（同日 r 只有 0.123）")
        # 刻意不設 alert 門檻：「韓國重挫 → 台灣次日」三個門檻的 bootstrap CI 全部跨零、
        # 下跌比僅 52~57%（基準 50%）⇒ inconclusive。設門檻等於假裝它有預測力。
        # 唯一可靠的用法是背離偵測：兩邊反向就不下注（739 交易日裡 0 例，無前例可循）。
        print("  只讀方向、不讀成強弱訊號：條件分布的 CI 全部跨零（見 docs/tw-swing-pipeline.md"
              " 的族群代理節）。**代理與台股同日反向時不下注。**")
    if "^VIX" in d:
        vix = d["^VIX"]
        # **看水位不看漲跌**：VIX 本身就是波動率，它的日漲跌率沒有 regime 意義，
        # 「20 還是 35」才有。費半崩兩位數而 VIX 卡在 20，是族群殺盤不是系統性風險。
        level = ("**系統性 risk-off**" if vix["收盤"] >= VIX_PANIC
                 else "殺盤仍侷限在族群，未擴散成系統性風險" if vix["收盤"] < 20
                 else "介於族群殺盤與系統性之間，看它往哪一邊走")
        print(f"VIX {vix['收盤']:.1f}（近 5 日 {vix['近5日'] * 100:+.1f}%）：{level}")
    if "TSM" in d:
        adr = d["TSM"]
        # **看變化率不要看絕對價**：ADR 對台股有長期溢價（實測約 +9.7%），
        # 用 `ADR × 匯率 ÷ 5` 得到的絕對價會比台股收盤高一截，那是溢價不是預期漲幅。
        print(f"台積電 ADR {adr['漲跌'] * 100:+.2f}% → 台積電開盤約 {adr['漲跌'] * 100:+.1f}%"
              f"（假設 ADR 溢價不變）")
        if a.tw_close and "TWD=X" in d:
            imp = adr_implied(adr["收盤"], d["TWD=X"]["收盤"])
            print(f"  ADR 折算絕對價 {imp:,.0f} 元 vs 台股收盤 {a.tw_close:,.0f} 元"
                  f" = 溢價 {imp / a.tw_close - 1:+.1%}（**這是溢價，不是預期漲幅**）")
    print("\n⚠ 韓股與台股**同時段**（韓 09:00-15:30 KST ＝ 台 08:00-14:30）：台北 08:00 前跑，"
          "韓股那組是**前一交易日**收盤；08:00 之後跑會混進當日盤中值（看上表日期辨識）。"
          "要判「今天韓國怎麼走」得在它開盤後另外查——這一格跟美股期貨同性質，本腳本抓不到。")
    print("\n這支腳本只給**收盤**數字。美股期貨與台指期夜盤要的是「現在」，日線抓不到"
          "（yfinance 在台北早上還沒切到次日場次，拿到的是昨天的期貨），需人工查即時報價——"
          "注意 17:00~21:30 的台指期夜盤**不含美股資訊**，別拿來算開盤缺口。"
          "\n開盤預期缺口 = 台指期夜盤收盤 ÷ 前一交易日加權指數收盤 − 1。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
