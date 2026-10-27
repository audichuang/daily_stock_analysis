"""scripts/verify_morning_calls.py：官方端點解析、夜盤／契約對齊、regime 驗證、計分資格、彙總門檻、append 去重（合成資料，不連網、不連 DB）。"""
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("verify_morning_calls", ROOT / "scripts" / "verify_morning_calls.py")
vmc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vmc)

D = dt.date(2099, 3, 4)
P = dt.date(2099, 3, 3)

TX_HEADER = ("交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未沖銷契約數,"
             "最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,價差對單式委託成交量")


def tx_line(day, month, session, open_, close, settle, volume):
    return (f"{day:%Y/%m/%d},TX,{month}  ,{open_},0,0,{close},0,0%,{volume},{settle},0,0,0,0,0,,{session},,")


def tx_csv(*lines):
    return "\n".join([TX_HEADER, *lines]) + "\n"


# ---------- 解析 ----------

def test_parse_hist_reads_roc_dates_and_skips_non_ok():
    payload = {"stat": "OK", "data": [["188/03/04", "1,000.00", "1,010.00", "990.00", "1,005.50"]]}
    assert vmc.parse_hist(payload) == {D: (1000.0, 1010.0, 990.0, 1005.5)}
    assert vmc.parse_hist({"stat": "很抱歉，沒有符合條件的資料!", "data": []}) == {}


def test_index_0905_rejects_a_response_for_another_day():
    rows = [["09:00:00", "1,000.00"], ["09:05:00", "1,020.00"]]
    ok = {"stat": "OK", "date": "20990304", "data": rows}
    assert vmc.parse_index_at(ok, D) == 1020.0
    # 端點遇到不合法日期會靜默回別天的資料：日期不符一定要拒收
    assert vmc.parse_index_at({**ok, "date": "20990303"}, D) is None
    assert vmc.parse_index_at({"stat": "OK", "date": "20990304", "data": rows[:1]}, D) is None


def test_parse_tx_drops_spreads_and_keeps_sessions():
    text = tx_csv(tx_line(D, "209904", "一般", 100, 101, 101, 5000),
                  f"{D:%Y/%m/%d},TX,209904/209905    ,10,0,0,12,-,-,500,-,-,0,0,0,0,,一般,40,")
    rows = vmc.parse_tx(text)
    assert [(r["contract"], r["session"]) for r in rows] == [("209904", "一般")]


def test_tx_measures_uses_same_contract_settle_and_night_row_of_the_day():
    text = tx_csv(
        tx_line(P, "209903", "一般", 0, 0, 900, 90000),     # 前一日近月是 03 月，但 D 當天量最大的是 04 月
        tx_line(P, "209904", "一般", 0, 0, 1000, 100),
        tx_line(D, "209903", "一般", 905, 0, 0, 10),
        tx_line(D, "209904", "一般", 1010, 0, 0, 80000),
        tx_line(D, "209904", "盤後", 0, 990, 0, 3000),      # D 的盤後列＝D 前一晚到 D 05:00 的夜盤
    )
    gap, night_close, night_chg, contract = vmc.tx_measures(vmc.parse_tx(text), D, P)
    assert contract == "209904"
    assert gap == pytest.approx(0.01)          # 1010 / 1000，不是 1010 / 900
    assert night_close == 990
    assert night_chg == pytest.approx(-0.01)


def test_tx_measures_missing_prev_settle_gives_none():
    text = tx_csv(tx_line(D, "209904", "一般", 1010, 0, 0, 80000))
    gap, _, _, contract = vmc.tx_measures(vmc.parse_tx(text), D, P)
    assert contract == "209904" and gap is None


# ---------- 判定 ----------

@pytest.mark.parametrize("breadth,vix,label", [
    (0.10, 35.0, "capitulation"),     # VIX>30 先判
    (0.10, 25.0, "broad_selloff"),
    (0.2499, 15.0, "broad_selloff"),
    (0.25, 15.0, "rotation"),         # 門檻是 <25%，剛好 25% 不算全面承壓
    (0.50, 15.0, "rotation"),         # 門檻是 >50%
    (0.5001, 19.9, "tailwind"),
    (0.60, 20.0, "rotation"),         # VIX 要 <20 才是順風
    (None, 15.0, None),
])
def test_regime_by_close_boundaries(breadth, vix, label):
    assert vmc.regime_by_close(breadth, vix) == label


def test_action_flag_is_descriptive_for_idle_and_contrarian_moves():
    assert vmc.action_flag("wait", 0.02) == "idle_on_big_move_up"
    assert vmc.action_flag("hold", -0.015) == "idle_on_big_move_down"
    assert vmc.action_flag("wait", 0.0149) is None
    assert vmc.action_flag("buy", -0.02) == "buy_on_big_drop"
    assert vmc.action_flag("buy", 0.02) is None
    assert vmc.action_flag("reduce", 0.02) == "reduce_on_big_rally"


def outcome(call, **kw):
    base = dict(prev=P, prev_close=1000.0, open_=1002.0, close=1020.0, idx_0905=1008.0,
                tx=(0.009, 1009.0, 0.004, "209904"), breadth=0.30, vix=18.0,
                now=dt.datetime(2099, 3, 4, 18, 0))
    return vmc.build_outcome(call, **{**base, **kw})


def test_build_outcome_errors_are_actual_minus_expected():
    row = outcome({"date": "2099-03-04", "regime": "rotation", "action": "wait",
                   "gap_expected": 0.005, "exclude_from_scoring": False})
    assert row["gap_open_official"] == pytest.approx(0.002)
    assert row["gap_0905"] == pytest.approx(0.008)
    assert row["err_gap_0905"] == pytest.approx(0.003)
    assert row["err_gap_open_official"] == pytest.approx(-0.003)
    assert row["night_spot_gap"] == pytest.approx(0.009)
    assert row["input_err"] == pytest.approx(-0.004)    # 預估 0.5% 比夜盤×現貨 0.9% 少抄了 0.4pp
    assert row["day_return"] == pytest.approx(0.02)
    assert row["regime_consistent"] is True and row["scorable"] is True
    assert row["action_flag"] == "idle_on_big_move_up"


@pytest.mark.parametrize("excl,scorable", [(False, True), (True, False), (None, False)])
def test_only_explicit_false_is_scorable(excl, scorable):
    call = {"date": "2099-03-04", "regime": "rotation", "action": "wait", "gap_expected": 0.0}
    if excl is not None:
        call["exclude_from_scoring"] = excl
    row = outcome(call)
    assert row["scorable"] is scorable
    if excl is None:
        assert "未標記" in row["note"]


def test_custom_regime_label_is_unscorable_not_inconsistent():
    row = outcome({"date": "2099-03-04", "regime": "relief_bounce", "action": "wait",
                   "gap_expected": 0.01, "exclude_from_scoring": False})
    assert row["regime_consistent"] is None
    assert "自創標籤" in row["note"]


# ---------- 彙總 ----------

def rows_from(pairs, measure="gap_0905"):
    """預估沒被修正過：寫下的 gap_expected 就是夜盤公式的原始值。"""
    return [{"gap_expected": e, "night_spot_gap": e, measure: a, "scorable": True} for e, a in pairs]


def test_small_sample_is_inconclusive_even_with_obvious_bias():
    rows = rows_from([(0.01, 0.02)] * 19)
    s = vmc.summarize(rows, "gap_0905")
    assert s["bias"] == pytest.approx(0.01)
    assert s["verdict"] == "inconclusive"


def test_enough_sample_with_ci_away_from_zero_is_significant():
    rng = np.random.default_rng(0)
    exp = rng.uniform(-0.02, 0.02, 30)
    rows = rows_from(zip(exp, exp + 0.01 + rng.normal(0, 0.001, 30)))
    s = vmc.summarize(rows, "gap_0905")
    assert s["verdict"] == "偏差顯著"


def test_unbiased_large_sample_stays_inconclusive():
    rng = np.random.default_rng(1)
    exp = rng.uniform(-0.02, 0.02, 40)
    rows = rows_from(zip(exp, exp + rng.normal(0, 0.003, 40)))
    assert vmc.summarize(rows, "gap_0905")["verdict"] == "inconclusive"


def test_scaling_applies_only_when_slope_ci_excludes_one():
    rng = np.random.default_rng(2)
    exp = rng.uniform(-0.02, 0.02, 30)
    half = vmc.summarize(rows_from(zip(exp, 0.5 * exp + rng.normal(0, 0.0005, 30))), "gap_0905")
    assert half["slope"] == pytest.approx(0.5, abs=0.05) and half["apply_scaling"] is True
    same = vmc.summarize(rows_from(zip(exp, exp + rng.normal(0, 0.0005, 30))), "gap_0905")
    assert same["apply_scaling"] is False
    few = vmc.summarize(rows_from(zip(exp[:10], 0.5 * exp[:10])), "gap_0905")
    assert few["apply_scaling"] is False


def test_summarize_skips_rows_missing_the_measure():
    rows = rows_from([(0.01, 0.012), (0.02, None)])
    assert vmc.summarize(rows, "gap_0905")["n"] == 1


# ---------- I/O ----------

def test_append_outcomes_never_rewrites_a_date(tmp_path):
    path = tmp_path / "out.jsonl"
    first = vmc.append_outcomes(path, [{"date": "2099-03-04", "v": 1}])
    again = vmc.append_outcomes(path, [{"date": "2099-03-04", "v": 2}, {"date": "2099-03-05", "v": 3}])
    assert [r["date"] for r in first] == ["2099-03-04"]
    assert [r["date"] for r in again] == ["2099-03-05"]
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [(r["date"], r["v"]) for r in lines] == [("2099-03-04", 1), ("2099-03-05", 3)]


class FakeFetcher:
    def __init__(self, sessions, idx_0905=1008.0):
        self.sessions, self.notes, self.idx_0905 = sessions, [], idx_0905

    def session(self, day):
        return self.sessions.get(day)

    def index_0905(self, day):
        return self.idx_0905

    def tx(self, day, prev):
        return (0.009, 1009.0, 0.004, "209904")


def test_compute_skips_unclosed_days_and_days_missing_from_db(monkeypatch):
    calls = [{"date": "2099-03-04", "regime": "rotation", "action": "wait", "gap_expected": 0.005,
              "exclude_from_scoring": False},
             {"date": "2099-03-05", "regime": "rotation", "action": "wait", "gap_expected": 0.0,
              "exclude_from_scoring": False},
             {"date": "2099-03-06", "regime": "rotation", "action": "wait", "gap_expected": 0.0,
              "exclude_from_scoring": False}]
    sessions = {D: (P, 1000.0, 1002.0, 1015.0), dt.date(2099, 3, 5): (D, 1015.0, 1015.0, 1016.0)}
    monkeypatch.setattr(vmc, "breadth_at", lambda engine, day: 0.3 if day == D else None)
    monkeypatch.setattr(vmc, "vix_prior", lambda engine, day: 18.0)
    logs = []
    rows = vmc.compute(calls, skip_dates=(), fetcher=FakeFetcher(sessions), engine=object(),
                       today=dt.date(2099, 3, 6), out=logs.append)
    assert [r["date"] for r in rows] == ["2099-03-04"]
    assert any("2099-03-05" in x and "DB" in x for x in logs)
    assert any("2099-03-06" in x and "官方日資料" in x for x in logs)


def test_compute_honours_skip_dates_and_future_dates(monkeypatch):
    calls = [{"date": "2099-03-04", "gap_expected": 0.0, "exclude_from_scoring": False},
             {"date": "2099-03-09", "gap_expected": 0.0, "exclude_from_scoring": False}]
    monkeypatch.setattr(vmc, "breadth_at", lambda engine, day: 0.3)
    monkeypatch.setattr(vmc, "vix_prior", lambda engine, day: 18.0)
    # 兩天都給得出行情：只有 skip_dates 與「還沒到的日期」這兩道會擋掉它們
    sessions = {D: (P, 1000.0, 1002.0, 1015.0), dt.date(2099, 3, 9): (D, 1015.0, 1015.0, 1016.0)}
    rows = vmc.compute(calls, skip_dates={"2099-03-04"}, fetcher=FakeFetcher(sessions), engine=object(),
                       today=dt.date(2099, 3, 6), out=lambda *_: None)
    assert rows == []


def test_brief_without_file_says_so(tmp_path):
    logs = []
    vmc.brief(tmp_path / "none.jsonl", out=logs.append)
    assert logs and "還沒有回驗結果" in logs[0]


def test_brief_marks_inconclusive_scaling_as_reminder_only(tmp_path):
    path = tmp_path / "out.jsonl"
    row = outcome({"date": "2099-03-04", "regime": "rotation", "action": "wait",
                   "gap_expected": 0.005, "exclude_from_scoring": False})
    vmc.append_outcomes(path, [row])
    logs = []
    vmc.brief(path, out=logs.append)
    text = "\n".join(logs)
    assert "inconclusive" in text and "只當提醒" in text


def test_load_calls_drops_closed_days_via_swing_read_log(tmp_path, monkeypatch):
    import verify_swing_decisions as vsd
    closed = tmp_path / "closed.txt"
    closed.write_text("2099-03-04  # test\n", encoding="utf-8")
    monkeypatch.setattr(vsd, "CLOSED_DATES", closed)
    log = tmp_path / "calls.jsonl"
    log.write_text("\n".join(json.dumps({"date": d, "gap_expected": 0.0, "exclude_from_scoring": False})
                             for d in ("2099-03-03", "2099-03-04")) + "\n", encoding="utf-8")
    calls, excluded = vmc.load_calls(log)
    assert [c["date"] for c in calls] == ["2099-03-03"] and excluded == 1


def test_scaling_is_estimated_on_the_raw_formula_not_on_corrected_forecasts():
    # 實際一律是夜盤公式值的一半；後 20 天的人已照建議把預估乘 0.5 寫進 gap_expected
    rng = np.random.default_rng(3)
    raw = rng.uniform(0.005, 0.02, 40)
    rows = [{"gap_expected": r if i < 20 else 0.5 * r, "night_spot_gap": r, "gap_0905": 0.5 * r, "scorable": True}
            for i, r in enumerate(raw)]
    s = vmc.summarize(rows, "gap_0905")
    assert s["slope"] == pytest.approx(0.5, abs=1e-9)   # 拿 gap_expected 回歸會得到約 0.6，下一次修過頭
    assert s["apply_scaling"] is True


def test_sparse_informative_predictors_never_certify_scaling():
    rows = [{"gap_expected": 0.0, "night_spot_gap": 0.0, "gap_0905": 0.0, "scorable": True}] * 19
    rows = rows + [{"gap_expected": 0.02, "night_spot_gap": 0.02, "gap_0905": 0.01, "scorable": True}]
    s = vmc.summarize(rows, "gap_0905")
    assert s["n_scale"] == 1
    assert s["slope_ci"] is None          # 約三成重抽算不出斜率：區間不存在，不能剩下的湊出 (0.5, 0.5)
    assert s["apply_scaling"] is False


def test_bootstrap_tolerates_a_few_undefined_resamples():
    vals = np.arange(50)
    ci = vmc._boot(vals, lambda a: float("nan") if a.sum() % 97 == 0 else float(a.mean()), n=400)
    assert ci is not None


def test_append_dedupes_within_one_batch(tmp_path):
    path = tmp_path / "out.jsonl"
    new = vmc.append_outcomes(path, [{"date": "2099-03-04", "v": 1}, {"date": "2099-03-04", "v": 2}])
    assert [r["v"] for r in new] == [1]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_append_waits_for_another_writer_holding_the_lock(tmp_path):
    """另一個行程持有鎖期間寫進同一天：等鎖的這邊放行後要看得到它、寫 0 筆。
    沒有鎖的話，子行程會先讀到空檔、照寫一筆，檔裡就有兩個 2099-03-04。"""
    import fcntl
    import subprocess
    import time
    path = tmp_path / "out.jsonl"
    code = ("import importlib.util,sys;"
            f"s=importlib.util.spec_from_file_location('v', {str(ROOT / 'scripts' / 'verify_morning_calls.py')!r});"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            "print(len(m.append_outcomes(sys.argv[1], [{'date': '2099-03-04'}])))")
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        child = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
        time.sleep(2)
        fh.write(json.dumps({"date": "2099-03-04"}) + "\n")
        fh.flush()
        fcntl.flock(fh, fcntl.LOCK_UN)
    out, _ = child.communicate(timeout=60)
    assert out.strip() == "0"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_temporarily_missing_measures_defer_then_write_after_the_window(monkeypatch):
    calls = [{"date": "2099-03-04", "regime": "rotation", "action": "wait", "gap_expected": 0.005,
              "exclude_from_scoring": False}]
    sessions = {D: (P, 1000.0, 1002.0, 1015.0)}
    monkeypatch.setattr(vmc, "breadth_at", lambda engine, day: 0.3)
    monkeypatch.setattr(vmc, "vix_prior", lambda engine, day: 18.0)
    logs = []
    soon = vmc.compute(calls, fetcher=FakeFetcher(sessions, idx_0905=None), engine=object(),
                       today=D + dt.timedelta(days=vmc.DEFER_DAYS), out=logs.append)
    assert soon == [] and any("延後寫入" in x for x in logs)
    late = vmc.compute(calls, fetcher=FakeFetcher(sessions, idx_0905=None), engine=object(),
                       today=D + dt.timedelta(days=vmc.DEFER_DAYS + 1), out=lambda *_: None)
    assert len(late) == 1 and "仍缺 gap_0905" in late[0]["note"]
    ok = vmc.compute(calls, fetcher=FakeFetcher(sessions), engine=object(), today=D, out=lambda *_: None)
    assert len(ok) == 1 and "note" not in ok[0]
