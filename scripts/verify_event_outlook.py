#!/usr/bin/env python3
"""事件展望回驗：財報日過後，比對報告當時的 expectation 與實際 surprise。

預測來自應用庫 analysis_history（唯讀），事後結果 append-only 寫 journal/event-outlook-outcomes.jsonl，
一個 (code, event_date) 一行、不重寫。預設唯讀，帶 --append 才寫檔。

口徑（事前定好，改了要在 journal/README.md 記）：
- 同一事件只取事件日之前最後一份報告，避免同事件多份報告灌大樣本。
- 只計 event_type=earnings 且 expectation 為 beat／inline／miss；insufficient_data 記錄但不計分。
- 實際結果取 earnings_history 中「季底早於事件日、相距不超過 MAX_REPORT_LAG_DAYS」最新一列。
  列還沒出現就先不寫（財報延期或來源未更新），下次再試。
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
MIN_SCORED = 20
SCORED = ("beat", "inline", "miss")


def _iso_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def select_predictions(rows: Iterable[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """rows 需含 report_id、code、created_at、outlook；回傳每事件最後一份事前報告，且事件日已過。"""
    latest: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        outlook = row.get("outlook") or {}
        event_date = _iso_date(outlook.get("event_date"))
        created = _iso_date(row.get("created_at"))
        if outlook.get("event_type") != "earnings" or event_date is None or created is None:
            continue
        # 日期比到日：事件當天才產出的報告可能已看到結果，一律不算事前
        if created >= event_date or event_date >= today:
            continue
        key = (row["code"], event_date.isoformat())
        if key not in latest or str(row["created_at"]) > str(latest[key]["created_at"]):
            latest[key] = row
    return list(latest.values())


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


def build_outcome(row: Dict[str, Any], fetch_history: Callable[[str], Any],
                  now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """回傳一行 outcome；實際結果還抓不到回 None（下次重試）。"""
    outlook = row["outlook"]
    expectation = outlook.get("expectation")
    base = {
        "code": row["code"], "event_date": outlook["event_date"], "report_id": row.get("report_id"),
        "predicted_at": str(row["created_at"]), "expectation": expectation, "confidence": outlook.get("confidence"),
        "evaluated_at": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
    }
    if expectation not in SCORED:
        return {**base, "scorable": False, "note": "insufficient_data"}
    actual = actual_for_event(fetch_history(row["code"]), date.fromisoformat(outlook["event_date"]))
    if actual is None:
        return None
    label = classify(actual["surprise_pct"])
    return {**base, **actual, "scorable": True, "actual": label, "hit": expectation == label,
            "always_beat_hit": label == "beat"}


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


def fetch_earnings_history(code: str) -> Any:
    import yfinance as yf

    from data_provider.yfinance_fundamental_adapter import _convert_to_yf_symbol

    try:
        return yf.Ticker(_convert_to_yf_symbol(code)).earnings_history
    except Exception as exc:
        print(f"[warn] {code} earnings_history 讀取失敗: {type(exc).__name__}", file=sys.stderr)
        return None


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
    done = {(o["code"], o["event_date"]) for o in existing}
    predictions = [p for p in select_predictions(load_prediction_rows(), date.today())
                   if (p["code"], p["outlook"]["event_date"]) not in done]
    cache: Dict[str, Any] = {}

    def fetch(code: str) -> Any:
        if code not in cache:
            cache[code] = fetch_earnings_history(code)
        return cache[code]

    new_rows = [o for o in (build_outcome(p, fetch) for p in predictions) if o is not None]
    if args.append and new_rows:
        append_outcomes(new_rows)
    render(summarize(existing + new_rows), len(predictions) - len(new_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
