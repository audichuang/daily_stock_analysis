#!/usr/bin/env python3
"""事件展望回驗：財報日過後，比對報告當時的 expectation 與實際 surprise。

預測來自應用庫 analysis_history（唯讀），事後結果 append-only 寫 journal/event-outlook-outcomes.jsonl，
一個 (code, quarter) 一行、不重寫。預設唯讀，帶 --append 才寫檔。

口徑（事前定好，改了要在 journal/README.md 記）：
- event_date 只是推估、會被更正，只拿來對到財季；去重鍵是股票＋財季，同一季只計一次。
- 財季取 earnings_history 中「季底早於 event_date、相距不超過 MAX_REPORT_LAG_DAYS」最新一列；
  列還沒出現就先不寫（財報延期或來源未更新），下次再試。
- 實際公告時間取 earnings_dates 中季底之後、Reported EPS 與該季 epsActual 相符的唯一一列；對不上就不計分、下次再試。
- 事前性比的是實際公告日：來源的時刻只是約略值（實測 TSM 有 02:00、20:00），報告須早於公告日當地 00:00。
  created_at 沒帶時區，一律當 UTC（比台北讀法晚 8 小時，只會少算不會把事後報告算進來）。
- 同一季只取最後一份事前報告；全部都在公告後就記 scorable=false。
- 只計 event_type=earnings 且 expectation 為 beat／inline／miss；insufficient_data 記錄但不計分。
- |surprise| 不超過 INLINE_BAND_PCT 算 inline。
- 命中率本身沒有意義（美股多數超預期），一律對照「永遠猜 beat」；n<MIN_SCORED 或區間跨零標 inconclusive。
"""
import argparse
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUTCOMES_PATH = ROOT / "journal" / "event-outlook-outcomes.jsonl"
INLINE_BAND_PCT = 2.0
MAX_REPORT_LAG_DAYS = 95
# Reported EPS 四捨五入到分，epsActual 同；容許一分內的進位差
EPS_MATCH_TOLERANCE = 0.011
MIN_SCORED = 20
SCORED = ("beat", "inline", "miss")


def _iso_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def actual_for_event(history: Any, event_date: date) -> Optional[Dict[str, Any]]:
    """history 是 yfinance earnings_history；索引是季底，不是公告日。"""
    import pandas as pd

    from data_provider.yfinance_fundamental_adapter import _safe_float

    if not isinstance(history, pd.DataFrame) or history.empty:
        return None
    best = None
    for quarter, row in history.iterrows():
        day = pd.Timestamp(quarter).date()
        if timedelta(0) < event_date - day <= timedelta(days=MAX_REPORT_LAG_DAYS) and (best is None or day > best[0]):
            best = (day, row)
    if best is None:
        return None
    surprise = _safe_float(best[1].get("surprisePercent"))
    actual = _safe_float(best[1].get("epsActual"))
    estimate = _safe_float(best[1].get("epsEstimate"))
    if surprise is None or actual is None:
        return None
    return {"quarter": best[0].isoformat(), "surprise_pct": round(surprise * 100, 2),
            "eps_actual": actual, "eps_estimate": estimate}


def classify(surprise_pct: float) -> str:
    if abs(surprise_pct) <= INLINE_BAND_PCT:
        return "inline"
    return "beat" if surprise_pct > 0 else "miss"


def announcement_for_quarter(dates: Any, quarter: str, eps_actual: float) -> Any:
    """回傳該季實際公告時間；無法唯一確認回 None，不猜。"""
    import pandas as pd

    from data_provider.yfinance_fundamental_adapter import _safe_float

    if not isinstance(dates, pd.DataFrame) or dates.empty:
        return None
    start = date.fromisoformat(quarter)
    matches = []
    for stamp, row in dates.iterrows():
        reported = _safe_float(row.get("Reported EPS"))
        day = pd.Timestamp(stamp).date()
        if (reported is not None and timedelta(0) < day - start <= timedelta(days=MAX_REPORT_LAG_DAYS)
                and abs(reported - eps_actual) <= EPS_MATCH_TOLERANCE):
            matches.append(pd.Timestamp(stamp))
    return matches[0] if len(matches) == 1 else None


def _created_utc(value: Any) -> Any:
    import pandas as pd

    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp


def _outcome_row(row: Dict[str, Any], quarter: str, announced: Any, now: datetime) -> Dict[str, Any]:
    outlook = row["outlook"]
    return {
        "code": row["code"], "quarter": quarter, "event_date": outlook.get("event_date"),
        "announced_at": announced.isoformat(), "report_id": row.get("report_id"),
        "predicted_at": str(row["created_at"]), "expectation": outlook.get("expectation"),
        "confidence": outlook.get("confidence"), "evaluated_at": now.isoformat(timespec="seconds"),
    }


def build_outcomes(rows: Iterable[Dict[str, Any]], fetch: Callable[[str], Dict[str, Any]],
                   done: Iterable[tuple] = (), now: Optional[datetime] = None) -> Dict[str, Any]:
    """rows 需含 report_id、code、created_at、outlook；fetch(code) 回 {history, dates}。

    回傳 {"outcomes": 新結果, "pending": 還不能結算的報告數}。全是 insufficient_data 的股票不連網。
    """
    now = now or datetime.now().astimezone()
    done = set(done)
    by_code: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        outlook = row.get("outlook") or {}
        if outlook.get("event_type") == "earnings" and _iso_date(outlook.get("event_date")) and row.get("created_at"):
            by_code.setdefault(row["code"], []).append(row)

    outcomes: List[Dict[str, Any]] = []
    pending = 0
    for code, code_rows in by_code.items():
        if not any(r["outlook"].get("expectation") in SCORED for r in code_rows):
            continue
        evidence = fetch(code) or {}
        groups: Dict[str, List[Dict[str, Any]]] = {}
        actuals: Dict[str, Dict[str, Any]] = {}
        for row in code_rows:
            actual = actual_for_event(evidence.get("history"), _iso_date(row["outlook"]["event_date"]))
            if actual is None:
                pending += 1
                continue
            groups.setdefault(actual["quarter"], []).append(row)
            actuals[actual["quarter"]] = actual
        for quarter, group in groups.items():
            if (code, quarter) in done:
                continue
            actual = actuals[quarter]
            announced = announcement_for_quarter(evidence.get("dates"), quarter, actual["eps_actual"])
            if announced is None:
                pending += len(group)
                continue
            cutoff = announced.normalize()
            ex_ante = [r for r in group if _created_utc(r["created_at"]) < cutoff]
            if not ex_ante:
                last = max(group, key=lambda r: _created_utc(r["created_at"]))
                outcomes.append({**_outcome_row(last, quarter, announced, now), "scorable": False,
                                 "note": "post_announcement"})
                continue
            last = max(ex_ante, key=lambda r: _created_utc(r["created_at"]))
            base = _outcome_row(last, quarter, announced, now)
            if base["expectation"] not in SCORED:
                outcomes.append({**base, "scorable": False, "note": "insufficient_data"})
                continue
            label = classify(actual["surprise_pct"])
            outcomes.append({**base, **actual, "scorable": True, "actual": label,
                             "hit": base["expectation"] == label, "always_beat_hit": label == "beat"})
    return {"outcomes": outcomes, "pending": pending}


def _percentile_ci(values: List[float]) -> tuple:
    ordered = sorted(values)
    return ordered[int(len(ordered) * 0.025)], ordered[min(int(len(ordered) * 0.975), len(ordered) - 1)]


def summarize(outcomes: Iterable[Dict[str, Any]], n_boot: int = 2000, seed: int = 42) -> Dict[str, Any]:
    """以股票為單位做 bootstrap：同一檔各季不是獨立樣本。"""
    all_rows = list(outcomes)
    rows = [o for o in all_rows if o.get("scorable") is True]
    summary: Dict[str, Any] = {"n": len(rows), "excluded": len(all_rows) - len(rows), "hit_rate": None,
                               "always_beat_rate": None, "diff_ci": None, "verdict": "inconclusive"}
    if not rows:
        return summary
    summary["hit_rate"] = sum(o["hit"] for o in rows) / len(rows)
    summary["always_beat_rate"] = sum(o["always_beat_hit"] for o in rows) / len(rows)
    by_code: Dict[str, List[float]] = {}
    for o in rows:
        by_code.setdefault(o["code"], []).append(float(o["hit"]) - float(o["always_beat_hit"]))
    codes = sorted(by_code)
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        sample = [d for code in rng.choices(codes, k=len(codes)) for d in by_code[code]]
        diffs.append(sum(sample) / len(sample))
    low, high = _percentile_ci(diffs)
    summary["diff_ci"] = (low, high)
    if len(rows) >= MIN_SCORED and (low > 0 or high < 0):
        summary["verdict"] = "better_than_always_beat" if low > 0 else "worse_than_always_beat"
    return summary


def read_outcomes(path: Path = OUTCOMES_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_outcomes(rows: List[Dict[str, Any]], path: Path = OUTCOMES_PATH) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_prediction_rows() -> List[Dict[str, Any]]:
    """唯讀查應用庫；不用 DatabaseManager（其 __init__ 會對正式庫 create_all、ALTER TABLE）。"""
    import os

    from sqlalchemy import text

    from portfolio_codes import _read_only_engine
    from src.services.event_outlook import extract_event_outlook

    url = (os.environ.get("STORAGE_DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit("STORAGE_DATABASE_URL 未設定：用 `uv run --env-file .env` 執行")
    rows = []
    with _read_only_engine(url).connect() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SET TRANSACTION READ ONLY"))
        query = text("select id, code, created_at, raw_result from analysis_history "
                     "where raw_result like '%\"event_outlook\"%'")
        for report_id, code, created_at, raw in conn.execute(query):
            try:
                outlook = extract_event_outlook(json.loads(raw))
            except (TypeError, ValueError):
                continue
            if outlook:
                rows.append({"report_id": report_id, "code": code, "created_at": created_at, "outlook": outlook})
    return rows


def fetch_evidence(code: str) -> Dict[str, Any]:
    import yfinance as yf

    from data_provider.yfinance_fundamental_adapter import _convert_to_yf_symbol

    try:
        ticker = yf.Ticker(_convert_to_yf_symbol(code))
        return {"history": ticker.earnings_history, "dates": ticker.get_earnings_dates(limit=12)}
    except Exception as exc:
        print(f"[warn] {code} 財報實績讀取失敗: {type(exc).__name__}", file=sys.stderr)
        return {}


def render(summary: Dict[str, Any], pending: int) -> None:
    print(f"可計分 {summary['n']} 筆；不計分 {summary['excluded']} 筆；待回驗 {pending} 筆")
    if summary["hit_rate"] is None:
        print("判定：inconclusive（沒有可計分樣本）")
        return
    print(f"命中率 {summary['hit_rate']:.1%}；對照「永遠猜 beat」{summary['always_beat_rate']:.1%}")
    low, high = summary["diff_ci"]
    print(f"差值 95% CI（依股票 bootstrap）：[{low:+.1%}, {high:+.1%}]")
    print(f"判定：{summary['verdict']}" + (f"（n<{MIN_SCORED} 或區間跨零）" if summary["verdict"] == "inconclusive" else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="事件展望回驗：expectation 對實際 surprise")
    parser.add_argument("--append", action="store_true", help=f"把新結果追加到 {OUTCOMES_PATH.name}（預設唯讀）")
    args = parser.parse_args()

    existing = read_outcomes()
    done = {(o["code"], o.get("quarter")) for o in existing}
    result = build_outcomes(load_prediction_rows(), fetch_evidence, done)
    if args.append and result["outcomes"]:
        append_outcomes(result["outcomes"])
    render(summarize(existing + result["outcomes"]), result["pending"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
