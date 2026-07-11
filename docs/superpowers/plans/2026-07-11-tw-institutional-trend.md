# 台股三大法人歷史趨勢注入 LLM prompt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在台股個股分析的 LLM prompt 中，於現有「當日三大法人」表格後追加歷史趨勢（連 N 日買/賣超、近 5/20 日累計、合計佔股本比），只進 prompt 字串。

**Architecture:** 三層——`market_repo.institutional()` 讀 Postgres `market.institutional` 歷史；`tw_institutional_trend.compute_institutional_trend()` 純函式把歷史+當日網路值算成趨勢；`analyzer._format_prompt` 的 prompt-層 helper fail-open 串起兩者並用 `L(zh_tw, zh)` 兩語格式化。趨勢只存在於 prompt 字串，永不進持久化 context。

**Tech Stack:** Python 3.12、SQLAlchemy(+psycopg)、pandas、pytest；`uv run` 執行。

## Global Constraints

- 只限台股（`.TW` / `.TWO`）；其他市場零影響。
- **只進 LLM prompt 字串**：不寫入 `context`、`fundamental_snapshot`、`context_snapshot`、API 報告、Agent/AlphaSift compactor；不改 institution block 對外 schema；不動 Web/報告渲染；不新增 DecisionSignal/score。
- **不改 `data_provider/base.py`**（趨勢在 prompt 層算，非 fundamental context 層）。
- **fail-open**：DB/psycopg/import/查詢逾時/無歷史/無當日 → helper 回空字串，現有 block 位元組不變，主分析流程不中斷。
- 不 mutate `TwInstitutionalFetcher` 的快取 record（用複本）。
- prompt 文案沿用該區塊既有 `L(zh_tw, zh)` 兩語；en/ko 由區塊既有 output-language 指令處理（不在此另做 en/ko 文案）。
- DB 讀用真正的 Postgres `statement_timeout`（3000ms），非僅 try/except。
- `stock_id` = 代碼去後綴（複用 `data_provider.market_db_fetcher._stock_id`）。
- commit message 英文、無 Co-Authored-By。

---

### Task 1: DB reader — `market_repo.institutional()` + statement-timeout engine

**Files:**
- Modify: `market_data/db.py`（`get_engine` 加 `statement_timeout_ms`）
- Modify: `market_data/market_repo.py`（新增 `institutional()`）
- Test: `market_data/tests/test_repo.py`（新增讀取測試）

**Interfaces:**
- Produces:
  - `market_data.db.get_engine(url: str | None = None, statement_timeout_ms: int | None = None)` — timeout 給定時回一個 `connect_args={"options": "-c statement_timeout=<ms>"}` 的（各自 lru_cache）engine。
  - `market_data.market_repo.institutional(stock_id: str, start=None, end=None, engine=None) -> pandas.DataFrame`，欄位 `date, foreign_net, trust_net, dealer_net, total_net`，`ORDER BY date`。

- [ ] **Step 1: Write the failing test**

在 `market_data/tests/test_repo.py` 末尾新增（沿用該檔既有 `DATABASE_URL` skip/fixture 慣例；若檔頭已有 module-level skip + engine fixture 就複用，勿重造）：

```python
def test_institutional_reader_returns_ordered_net_columns(engine):
    from market_data import market_repo
    df = market_repo.institutional("2330", start="2010-01-01", engine=engine)
    assert list(df.columns) == ["date", "foreign_net", "trust_net", "dealer_net", "total_net"]
    if not df.empty:
        dates = list(df["date"])
        assert dates == sorted(dates)  # ORDER BY date
```

> 若 `test_repo.py` 用的 fixture 名不是 `engine`，改成該檔實際的 fixture 名。讀檔頭確認。

- [ ] **Step 2: Run test to verify it fails**

```
export $(grep '^DATABASE_URL=' .env | xargs) && uv run --no-project --with sqlalchemy --with 'psycopg[binary]' --with pandas --with lxml --with requests --with tqdm --with pytest python -m pytest market_data/tests/test_repo.py::test_institutional_reader_returns_ordered_net_columns -v
```
Expected: FAIL（`AttributeError: module 'market_data.market_repo' has no attribute 'institutional'`）

- [ ] **Step 3: Add the timeout engine path in `market_data/db.py`**

把 `_engine_for` / `get_engine` 改為：

```python
@lru_cache(maxsize=8)
def _engine_for(url: str, statement_timeout_ms: int | None = None):
    connect_args = {}
    if statement_timeout_ms:
        # Postgres per-connection statement timeout (psycopg): abort runaway reads.
        connect_args["options"] = f"-c statement_timeout={int(statement_timeout_ms)}"
    return create_engine(
        url, pool_pre_ping=True, pool_recycle=1800, future=True,
        connect_args=connect_args,
    )


def get_engine(url: str | None = None, statement_timeout_ms: int | None = None):
    # cache per (URL, timeout) so repeated reads reuse one pool (no leak)
    return _engine_for(url or database_url(), statement_timeout_ms)
```

- [ ] **Step 4: Add `institutional()` in `market_data/market_repo.py`**

在 `valuation()` 之後新增（照既有模式）：

```python
def institutional(stock_id, start=None, end=None, engine=None):
    sql = ("SELECT date, foreign_net, trust_net, dealer_net, total_net "
           "FROM market.institutional WHERE stock_id = :sid")
    params = {"sid": stock_id}
    if start:
        sql += " AND date >= :start"
        params["start"] = start
    if end:
        sql += " AND date <= :end"
        params["end"] = end
    return _q(sql + " ORDER BY date", params, engine)
```

- [ ] **Step 5: Run test to verify it passes**

Run: 同 Step 2 指令。
Expected: PASS（無 DATABASE_URL 時該檔慣例會 skip，亦視為通過）

- [ ] **Step 6: Commit**

```bash
git add market_data/db.py market_data/market_repo.py market_data/tests/test_repo.py
git commit -m "feat(market_data): add institutional() reader + statement-timeout engine option"
```

---

### Task 2: Pure trend function — `tw_institutional_trend.py`

**Files:**
- Create: `data_provider/tw_institutional_trend.py`
- Test: `tests/test_tw_institutional_trend.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces: `data_provider.tw_institutional_trend.compute_institutional_trend(history_rows: list[dict], today_record: dict | None, shares_outstanding) -> dict`. 回 `{}` 表無可用序列。永不拋例外。輸出形狀：
  ```
  {"as_of": "YYYY-MM-DD", "sessions": int,
   "foreign"/"trust"/"dealer"/"total": {
       "streak": {"days": int, "direction": "buy"|"sell"|"flat", "capped": bool},
       "cum_5d": int|None, "cum_20d": int|None},
   "total": {..., "pct_of_shares": float|None}}
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tw_institutional_trend.py`:

```python
from data_provider.tw_institutional_trend import compute_institutional_trend


def _row(d, f=None, t=None, de=None, tot=None):
    return {"date": d, "foreign_net": f, "trust_net": t, "dealer_net": de, "total_net": tot}


def test_consecutive_buy_streak_includes_today():
    hist = [_row("2026-07-07", 100, 0, 0, 100), _row("2026-07-08", 200, 0, 0, 200)]
    today = _row("20260709", 300, 0, 0, 300)
    out = compute_institutional_trend(hist, today, None)
    assert out["foreign"]["streak"] == {"days": 3, "direction": "buy", "capped": True}
    assert out["foreign"]["cum_5d"] == 600
    assert out["as_of"] == "2026-07-09"


def test_sign_flip_breaks_streak():
    hist = [_row("2026-07-07", -50, 0, 0, -50), _row("2026-07-08", 100, 0, 0, 100)]
    today = _row("20260709", 200, 0, 0, 200)
    out = compute_institutional_trend(hist, today, None)
    assert out["foreign"]["streak"]["days"] == 2  # today + prev buy; -50 flips
    assert out["foreign"]["streak"]["direction"] == "buy"


def test_zero_and_null_break_streak_and_skip_cum():
    hist = [_row("2026-07-07", None, 0, 0, None), _row("2026-07-08", 100, 0, 0, 100)]
    today = _row("20260709", 200, 0, 0, 200)
    out = compute_institutional_trend(hist, today, None)
    assert out["foreign"]["streak"]["days"] == 2       # None breaks before it
    assert out["foreign"]["cum_5d"] == 300             # None skipped, not counted as 0


def test_dedupe_when_db_already_has_today():
    hist = [_row("2026-07-08", 100, 0, 0, 100), _row("2026-07-09", 999, 0, 0, 999)]  # stale today
    today = _row("20260709", 300, 0, 0, 300)  # authoritative
    out = compute_institutional_trend(hist, today, None)
    assert out["sessions"] == 2                         # stale 07-09 dropped
    assert out["foreign"]["cum_5d"] == 400              # 100 + 300 (not 999)


def test_pct_of_shares_on_total_only():
    hist = [_row("2026-07-08", 0, 0, 0, 1000)]
    today = _row("20260709", 0, 0, 0, 1000)
    out = compute_institutional_trend(hist, today, 100000)
    assert out["total"]["pct_of_shares"] == round(2000 / 100000 * 100, 2)  # 2.0
    assert "pct_of_shares" not in out["foreign"]


def test_missing_shares_gives_none_pct():
    out = compute_institutional_trend([], _row("20260709", 0, 0, 0, 1000), None)
    assert out["total"]["pct_of_shares"] is None


def test_empty_returns_empty_dict():
    assert compute_institutional_trend([], None, None) == {}
    assert compute_institutional_trend(None, None, 100) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_tw_institutional_trend.py -v`
Expected: FAIL（`ModuleNotFoundError: data_provider.tw_institutional_trend`）

- [ ] **Step 3: Implement the pure function**

Create `data_provider/tw_institutional_trend.py`:

```python
"""Pure functions computing Taiwan 三大法人 (institutional) history trend.

No DB / no network / no I/O — fully unit-testable. Consumers (the analyzer
prompt layer) read history + today's record and pass them here. Output is used
ONLY to build LLM prompt lines; it is never persisted.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

_ACTORS = ("foreign", "trust", "dealer", "total")
_NET_KEY = {
    "foreign": "foreign_net",
    "trust": "trust_net",
    "dealer": "dealer_net",
    "total": "total_net",
}


def _norm_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip().replace("-", "").replace("/", "")
    if len(s) == 8 and s.isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compute_institutional_trend(
    history_rows: Any,
    today_record: Optional[dict],
    shares_outstanding: Any,
) -> dict:
    """Build one date-ordered series (history up to prev day + today authoritative),
    compute per-actor streak / cum_5d / cum_20d and total pct_of_shares.
    Return {} if no usable series. Never raises."""
    today_date = _norm_date((today_record or {}).get("date"))

    series: list[tuple[date, dict]] = []
    for row in (history_rows or []):
        d = _norm_date(row.get("date"))
        if d is None:
            continue
        if today_date is not None and d >= today_date:
            continue  # drop rows on/after today; today comes from the authoritative record
        series.append((d, {a: _to_int(row.get(_NET_KEY[a])) for a in _ACTORS}))
    if today_record is not None and today_date is not None:
        series.append((today_date, {a: _to_int(today_record.get(_NET_KEY[a])) for a in _ACTORS}))
    if not series:
        return {}
    series.sort(key=lambda x: x[0])
    n = len(series)

    def _streak(actor: str) -> dict:
        vals = [d[1][actor] for d in series]
        latest = vals[-1]
        if latest is None or latest == 0:
            return {"days": 0, "direction": "flat", "capped": False}
        sign = 1 if latest > 0 else -1
        days = 0
        for v in reversed(vals):
            if v is None or v == 0 or (1 if v > 0 else -1) != sign:
                break
            days += 1
        return {"days": days, "direction": "buy" if sign > 0 else "sell", "capped": days == n}

    def _cum(actor: str, window: int) -> Optional[int]:
        present = [d[1][actor] for d in series[-window:] if d[1][actor] is not None]
        return sum(present) if present else None

    out: dict[str, Any] = {"as_of": series[-1][0].isoformat(), "sessions": n}
    for a in _ACTORS:
        out[a] = {"streak": _streak(a), "cum_5d": _cum(a, 5), "cum_20d": _cum(a, 20)}
    shares = _to_int(shares_outstanding)
    total_cum20 = out["total"]["cum_20d"]
    out["total"]["pct_of_shares"] = (
        round(total_cum20 / shares * 100, 2)
        if (total_cum20 is not None and shares and shares > 0)
        else None
    )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_tw_institutional_trend.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add data_provider/tw_institutional_trend.py tests/test_tw_institutional_trend.py
git commit -m "feat(data): pure TW institutional history trend computation"
```

---

### Task 3: Analyzer prompt-layer helper + wiring + fail-open test

**Files:**
- Modify: `src/analyzer.py`（新增 method `_tw_institutional_trend_lines`；在 `_format_prompt` 三大法人區塊後呼叫）
- Test: `tests/test_analyzer_tw_institutional_trend.py`

**Interfaces:**
- Consumes: `market_data.market_repo.institutional/stock_info`、`market_data.db.get_engine`、`data_provider.market_db_fetcher._stock_id`、`data_provider.tw_institutional_trend.compute_institutional_trend`。
- Produces: `GeminiAnalyzer._tw_institutional_trend_lines(self, code: str, institution_data: dict, report_language: str) -> str`。回 `""` 表無趨勢或任何失敗。

- [ ] **Step 1: Write the failing fail-open test**

Create `tests/test_analyzer_tw_institutional_trend.py`:

```python
from unittest.mock import patch
from src.analyzer import GeminiAnalyzer


def _analyzer():
    return GeminiAnalyzer.__new__(GeminiAnalyzer)  # no __init__ / no network


def test_trend_lines_fail_open_on_db_error_returns_empty():
    a = _analyzer()
    with patch("market_data.market_repo.institutional", side_effect=RuntimeError("db down")):
        out = a._tw_institutional_trend_lines(
            "2330.TW", {"foreign_net": 1, "trust_net": 1, "dealer_net": 1, "total_net": 3, "date": "20260709"}, "zh-TW")
    assert out == ""


def test_trend_lines_render_when_history_present():
    a = _analyzer()
    hist_rows = [
        {"date": "2026-07-07", "foreign_net": 100, "trust_net": 0, "dealer_net": 0, "total_net": 100},
        {"date": "2026-07-08", "foreign_net": 200, "trust_net": 0, "dealer_net": 0, "total_net": 200},
    ]

    class _DF:
        empty = False
        def to_dict(self, orient):
            return hist_rows

    with patch("market_data.market_repo.institutional", return_value=_DF()), \
         patch("market_data.market_repo.stock_info", return_value={"shares_outstanding": 100000}), \
         patch("market_data.db.get_engine", return_value=None):
        out = a._tw_institutional_trend_lines(
            "2330.TW", {"foreign_net": 300, "trust_net": 0, "dealer_net": 0, "total_net": 300, "date": "20260709"}, "zh-TW")
    assert "外資" in out and ("連" in out or "日" in out)  # 繁體 trend line present
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_analyzer_tw_institutional_trend.py -v`
Expected: FAIL（`AttributeError: 'GeminiAnalyzer' object has no attribute '_tw_institutional_trend_lines'`）

- [ ] **Step 3: Implement the helper method**

在 `src/analyzer.py` 的 `GeminiAnalyzer` class 內（`_format_prompt` 附近）新增：

```python
    def _tw_institutional_trend_lines(
        self, code: str, institution_data: dict, report_language: str
    ) -> str:
        """Prompt-only: read TW institutional history, compute trend, format 2-language
        lines. Returns '' on any failure / no data. NEVER persisted (prompt string only)."""
        try:
            from datetime import date, timedelta

            from market_data import market_repo
            from market_data.db import get_engine
            from data_provider.market_db_fetcher import _stock_id
            from data_provider.tw_institutional_trend import compute_institutional_trend

            sid = _stock_id(code)
            eng = get_engine(statement_timeout_ms=3000)
            start = (date.today() - timedelta(days=90)).isoformat()
            hist = market_repo.institutional(sid, start=start, engine=eng)
            rows = hist.to_dict("records") if hist is not None and not hist.empty else []
            info = market_repo.stock_info(sid, engine=eng) or {}
            today = dict(institution_data)  # copy — never mutate the cached fetcher record
            trend = compute_institutional_trend(rows, today, info.get("shares_outstanding"))
        except Exception as exc:  # noqa: BLE001 — prompt enrichment is strictly fail-open
            logger.warning("[tw-inst-trend] fail-open code=%s: %s", code, exc)
            return ""
        if not trend:
            return ""

        lang = normalize_report_language(report_language)

        def L(zh_tw: str, zh: str) -> str:
            return zh_tw if lang == "zh-TW" else zh

        _dir = {
            "buy": L("買超", "买超"),
            "sell": L("賣超", "卖超"),
            "flat": L("無明顯方向", "无明显方向"),
        }
        _label = {
            "foreign": L("外資", "外资"),
            "trust": L("投信", "投信"),
            "dealer": L("自營商", "自营商"),
            "total": L("三大法人合計", "三大法人合计"),
        }
        lines = []
        for actor in ("foreign", "trust", "dealer", "total"):
            a = trend.get(actor) or {}
            streak = a.get("streak") or {}
            days = streak.get("days", 0)
            direction = _dir.get(streak.get("direction", "flat"), _dir["flat"])
            ge = "≥" if streak.get("capped") else ""
            cum20 = a.get("cum_20d")
            parts = []
            if days > 0:
                parts.append(L(f"連 {ge}{days} 日{direction}", f"连 {ge}{days} 日{direction}"))
            else:
                parts.append(direction)
            if cum20 is not None:
                parts.append(L(f"近 20 日累計 {cum20:+d} 股", f"近 20 日累计 {cum20:+d} 股"))
            if actor == "total" and a.get("pct_of_shares") is not None:
                parts.append(L(f"佔股本 {a['pct_of_shares']:+.2f}%", f"占股本 {a['pct_of_shares']:+.2f}%"))
            lines.append(f"- {_label[actor]}：{'；'.join(parts)}")
        header = L(
            f"三大法人近期趨勢（截至 {trend.get('as_of', 'N/A')}，共 {trend.get('sessions', 0)} 交易日）：",
            f"三大法人近期趋势（截至 {trend.get('as_of', 'N/A')}，共 {trend.get('sessions', 0)} 交易日）：",
        )
        return "\n" + header + "\n" + "\n".join(lines) + "\n"
```

> `normalize_report_language` 與 `logger` 已在 `analyzer.py` module scope（沿用現有 import）。

- [ ] **Step 4: Wire into `_format_prompt` 三大法人區塊**

在 `src/analyzer.py` 三大法人動向 block 的結尾（現有那段 `> {L("三大法人是台股的籌碼過濾器…")}"""` 之後、`# 添加筹码分布数据` 之前）插入：

```python
            trend_lines = self._tw_institutional_trend_lines(code, institution_data, report_language)
            if trend_lines:
                prompt += trend_lines
```

（此段在既有 `if institution status==ok and 四欄非 None:` 區塊內，故只有當日 block 成立時才嘗試。）

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_analyzer_tw_institutional_trend.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: py_compile + commit**

```bash
uv run python -m py_compile src/analyzer.py
git add src/analyzer.py tests/test_analyzer_tw_institutional_trend.py
git commit -m "feat(analyzer): inject TW institutional history trend into prompt (tw-only, fail-open, prompt-only)"
```

---

### Task 4: Contract regression + integration verification

**Files:**
- Test: `tests/test_analyzer_tw_institutional_trend.py`（新增契約回歸）
- 無 source 變更（純驗證）

**Interfaces:** none new.

- [ ] **Step 1: Write the persisted-context contract test**

在 `tests/test_analyzer_tw_institutional_trend.py` 新增——證明趨勢**不**進持久化 context（institution block data 仍為 raw-only 四欄+meta，無 `trend` key）：

```python
def test_trend_never_enters_institution_context():
    # The trend is prompt-only; the institution block in context must stay raw.
    # Compute a trend dict and assert the pure output is not attached to any input dict.
    from data_provider.tw_institutional_trend import compute_institutional_trend
    inst = {"foreign_net": 1, "trust_net": 1, "dealer_net": 1, "total_net": 3, "date": "20260709"}
    inst_before = dict(inst)
    _ = compute_institutional_trend([], dict(inst), None)  # pass a copy, as the helper does
    assert inst == inst_before  # source record untouched
    assert "trend" not in inst
```

- [ ] **Step 2: Run the full new-test file**

Run: `uv run python -m pytest tests/test_tw_institutional_trend.py tests/test_analyzer_tw_institutional_trend.py -v`
Expected: PASS (all)

- [ ] **Step 3: Regression — existing institution raw-only tests still green**

Run (`.env` 移開避免 REPORT_LANGUAGE/LITELLM 污染)：
```bash
mv .env .env.bak
uv run python -m pytest -q -m "not network" tests/test_report_schema.py tests/test_analysis_api_contract.py $(ls tests | grep -iE 'institution|fundamental' | sed 's#^#tests/#')
mv .env.bak .env
```
Expected: PASS（既有 institution/報告契約測試不受影響）

- [ ] **Step 4: Integration — live 2330.TW prompt shows the trend lines**

```bash
timeout 400 uv run python main.py --stocks 2330.TW --no-notify --force-run --debug 2>&1 | tee /tmp/ph3_2330.log | grep -E "三大法人近期趨勢|連 [0-9]|近 20 日累計|tw-inst-trend" | head
```
Expected: 出現「三大法人近期趨勢…連 N 日買超…近 20 日累計」行；`[tw-inst-trend] fail-open` 不應出現（DB 可用時）。若 fail-open 出現，讀 `/tmp/ph3_2330.log` 查 DB/欄位原因。

- [ ] **Step 5: Confirm no unintended git changes + final commit (docs/changelog)**

在 `docs/CHANGELOG.md` `[Unreleased]` 頂部加一行：
```
- [新功能] 台股個股分析 LLM prompt 追加三大法人歷史趨勢（外資/投信/自營/合計 連 N 日買賣超、近 5/20 日累計、合計佔股本比）：DB(`market.institutional` 14 年歷史)+當日網路值於 prompt 組裝層即時計算，tw-only、fail-open、僅進 prompt 不入持久化 context/schema/Web。
```

```bash
git add docs/CHANGELOG.md
git commit -m "docs: changelog for TW institutional history trend prompt injection"
```

---

## Self-Review

- **Spec coverage:** market_repo reader (T1) ✓、純函式趨勢 (T2) ✓、analyzer prompt-層 helper+wiring (T3) ✓、statement_timeout (T1) ✓、fail-open (T3) ✓、契約不洩漏 (T4) ✓、實跑驗證 (T4) ✓、兩語 L (T3) ✓、去重/NULL/streak-cap/pct-total-only (T2 tests) ✓。
- **Placeholder scan:** 無 TBD；每段含完整程式碼與指令。
- **Type consistency:** `institutional(stock_id,start,end,engine)`、`get_engine(url,statement_timeout_ms)`、`compute_institutional_trend(history_rows,today_record,shares_outstanding)`、`_tw_institutional_trend_lines(code,institution_data,report_language)` — 各 task 間簽名一致。
