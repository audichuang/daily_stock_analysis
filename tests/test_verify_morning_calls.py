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

    def history(self, day):
        hist, _ = mk_hist([1, 0] * 25, start=dt.date(2099, 1, 1))   # 都早於 D
        return hist


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


# ---------- 機率計分：基準、Brier、bootstrap ----------

def mk_hist(ys, start=dt.date(2098, 1, 1)):
    """ys: 逐日 close_up 序列；oc_up／gap_up 取同值，方便手算。回 (hist, 下一個日期)。"""
    hist = [{"date": start + dt.timedelta(days=i), "close_up": y, "oc_up": y, "gap_up": y} for i, y in enumerate(ys)]
    return hist, start + dt.timedelta(days=len(ys))


def test_hist_targets_derives_three_directions_from_ohlc():
    merged = {dt.date(2099, 3, 3): (0, 0, 0, 100.0), dt.date(2099, 3, 4): (101.0, 0, 0, 100.5),
              dt.date(2099, 3, 5): (99.0, 0, 0, 100.5)}
    got = vmc.hist_targets(merged)
    assert [(h["date"].day, h["close_up"], h["oc_up"], h["gap_up"]) for h in got] == [
        (4, 1, 0, None),     # 收 100.5>100；收 100.5<開 101；gap_up 沒有 09:05 歷史、不拿官方開盤頂替
        (5, 0, 1, None),     # 收平前收（不算上漲）；收 100.5>開 99
    ]


def test_baseline_a_and_b_use_laplace_rolling_frequencies():
    # 歷史 1,1,0,1,1,0（最近一天＝0）；forecast 日是下一天
    hist, day = mk_hist([1, 1, 0, 1, 1, 0])
    b = vmc.baseline_fields(day, hist, None)
    assert b["base_a_dir_close_up"] == 1
    assert b["base_a_p_close_up"] == pytest.approx((4 + 1) / (6 + 2))
    # 昨日＝0；歷史上昨日為 0 的下一天只有 idx2→3 一次（idx5 是最後一天沒有下一天）
    # 配對 (a,b)：a=0 的有 idx2(→1)；所以 n=1, ups=1
    assert b["base_b_dir_close_up"] == 0
    assert b["base_b_p_close_up"] == pytest.approx((1 + 1) / (1 + 2))
    assert b["base_c_p_close_up"] is None and b["base_c_dir_close_up"] is None   # sp 不可用：留空不當 0
    assert b["base_n_close_up"] == 6


def test_baseline_c_conditions_on_sp_direction_before_forecast_day():
    hist, day = mk_hist([1, 0, 1, 1])
    d0 = hist[0]["date"]
    one = dt.timedelta(days=1)
    # 台股日 d0..d3 看到的 S&P（date < 台股日的最近一筆）依序是 1,0,1,1；forecast 日 d4 看到 d3 的 0
    sp = [(d0 - one, 1), (d0, 0), (d0 + one, 1), (d0 + 2 * one, 1), (d0 + 3 * one, 0)]
    b = vmc.baseline_fields(day, hist, sp)
    assert b["base_c_dir_close_up"] == 0
    assert b["base_c_p_close_up"] == pytest.approx((0 + 1) / (1 + 2))   # 歷史上 S&P=0 只有 d1（當天收跌）


def test_baseline_never_uses_forecast_day_or_later_data():
    hist, day = mk_hist([1, 0, 1, 0])
    base = vmc.baseline_fields(day, hist, None)
    # forecast 當日與之後的資料即使存在於 hist（Fetcher 會抓到當月整月）也不得影響基準
    leak = hist + [{"date": day, "close_up": 1, "oc_up": 1, "gap_up": 1},
                   {"date": day + dt.timedelta(days=1), "close_up": 1, "oc_up": 1, "gap_up": 1}]
    assert vmc.baseline_fields(day, leak, None) == base
    assert base["base_a_p_close_up"] == pytest.approx(3 / 6)
    assert base["base_n_close_up"] == 4


def test_baseline_window_keeps_only_the_latest_252_prior_days():
    hist, day = mk_hist([0] * 10 + [1] * vmc.ROLL_WINDOW)
    b = vmc.baseline_fields(day, hist, None)
    assert b["base_n_close_up"] == vmc.ROLL_WINDOW
    assert b["base_a_p_close_up"] == pytest.approx((vmc.ROLL_WINDOW + 1) / (vmc.ROLL_WINDOW + 2))


def test_baseline_empty_history_is_none_not_zero():
    b = vmc.baseline_fields(D, [], None)
    assert b["base_a_p_close_up"] is None and b["base_n_close_up"] == 0


def test_sp_directions_and_lookup_is_strictly_before_the_day():
    d = dt.date(2099, 3, 2)
    sp = vmc.sp_directions([(d, 100.0), (d + dt.timedelta(days=1), 101.0), (d + dt.timedelta(days=2), 99.0)])
    assert sp == [(d + dt.timedelta(days=1), 1), (d + dt.timedelta(days=2), 0)]
    assert vmc._sp_dir_before(sp, d + dt.timedelta(days=2)) == 1      # 當天的 S&P 收盤還沒發生
    assert vmc._sp_dir_before(sp, d + dt.timedelta(days=1)) is None
    # 收平不算上漲（與 hist_targets 的 `>` 同一口徑）
    assert vmc.sp_directions([(d, 100.0), (d + dt.timedelta(days=1), 100.0)]) == [(d + dt.timedelta(days=1), 0)]


def prob_rows(spec):
    """spec: [(p, y, base_a_p, base_a_dir)]，其餘基準留空。"""
    rows = []
    for i, (p, y, bp, bd) in enumerate(spec):
        rows.append({"date": f"2099-04-{i + 1:02d}", "p_close_up": p, "y_close_up": y,
                     "base_a_p_close_up": bp, "base_a_dir_close_up": bd})
    return rows


def test_brier_and_paired_differences_on_fixed_data():
    rows = prob_rows([(0.8, 1, 0.5, 1), (0.2, 0, 0.5, 1), (0.6, 0, 0.5, 1), (0.4, 1, 0.5, 1)])
    s = vmc.prob_summary(rows, "close_up")
    assert s["n"] == 4
    assert s["brier"] == pytest.approx((0.04 + 0.04 + 0.36 + 0.36) / 4)
    a = s["baselines"]["a"]
    assert a["brier"] == pytest.approx(0.25)
    assert a["d_mean"] == pytest.approx(0.25 - 0.20)
    # 模型方向 p>0.5：命中 1,1,0,0；基準恆看漲（y=1,0,0,1）命中 1,0,0,1 → a_i = 0,1,0,-1
    assert a["a_mean"] == pytest.approx(0.0)
    assert s["bias"] == pytest.approx(0.5 - 0.5)
    assert s["baselines"]["b"]["n_brier"] == 0 and "無機率基準" in s["baselines"]["b"]["verdict"]


def test_small_sample_reports_bias_and_stays_inconclusive():
    rows = prob_rows([(0.7, 1, 0.5, 1)] * 19)
    s = vmc.prob_summary(rows, "close_up")
    assert s["bias"] == pytest.approx(-0.3) and s["baselines"]["a"]["verdict"] == "inconclusive"
    logs = []
    vmc.render_prob_summary(rows, logs.append)
    text = "\n".join(logs)
    assert "只報整體偏差" in text and "d̄" not in text


def test_clear_skill_with_enough_samples_beats_baseline_and_flat_difference_does_not():
    rng = np.random.default_rng(5)
    y = rng.integers(0, 2, 60)
    good = [(0.85 if v else 0.15, int(v), 0.5, 1) for v in y]
    assert vmc.prob_summary(prob_rows(good), "close_up")["baselines"]["a"]["verdict"] == "模型優於基準"
    # 與基準同分：d_i 全為 0，CI 跨零（含端點）
    same = [(0.5, int(v), 0.5, 1) for v in y]
    assert vmc.prob_summary(prob_rows(same), "close_up")["baselines"]["a"]["verdict"] == "inconclusive"
    worse = [(0.15 if v else 0.85, int(v), 0.5, 1) for v in y]
    assert vmc.prob_summary(prob_rows(worse), "close_up")["baselines"]["a"]["verdict"] == "模型劣於基準"


def test_old_rows_without_p_fields_are_skipped_not_crashing():
    rows = prob_rows([(0.6, 1, 0.5, 1)] * 3) + [{"date": "2099-03-01", "gap_0905": 0.01},
                                              {"date": "2099-03-02", "p_close_up": None, "y_close_up": 1}]
    s = vmc.prob_summary(rows, "close_up")
    assert s["n"] == 3 and s["n_skipped"] == 2
    empty = vmc.prob_summary([{"date": "2099-03-01"}], "oc_up")
    assert empty["n"] == 0
    logs = []
    vmc.render_summary([{"date": "2099-03-01", "scorable": True, "gap_expected": 0.0, "gap_0905": 0.0,
                         "night_spot_gap": 0.0, "gap_open_official": 0.0, "gap_tx_open": 0.0}], logs.append)
    assert any("沒有帶 p_close_up" in x for x in logs)


def test_circular_block_bootstrap_wraps_around_and_is_deterministic():
    vals = [1.0] * 30
    assert vmc._cbb_ci(vals) == (1.0, 1.0)
    assert vmc._cbb_ci(vals[:1]) is None
    v = list(np.random.default_rng(0).normal(0, 1, 40))
    assert vmc._cbb_ci(v) == vmc._cbb_ci(v)


def test_build_outcome_carries_probs_actuals_and_rejects_percentages():
    call = {"date": "2099-03-04", "regime": "rotation", "action": "wait", "gap_expected": 0.005,
            "exclude_from_scoring": False, "p_close_up": 0.4, "p_oc_up": 62, "p_gap_up": 0.7,
            "model_version": "claude", "skill_version": "abc"}
    row = outcome(call)
    assert (row["p_close_up"], row["p_gap_up"]) == (0.4, 0.7)
    assert row["p_oc_up"] is None and "p_oc_up=62" in row["note"]    # 百分數不是機率：當缺、記原因
    # 收 1020>前收 1000；收 1020>開 1002；09:05 1008>1000
    assert (row["y_close_up"], row["y_oc_up"], row["y_gap_up"]) == (1, 1, 1)
    assert row["model_version"] == "claude" and row["skill_version"] == "abc"
    assert row["night_dir_up"] == 1 and row["base_d_dir_close_up"] == 1 and row["base_d_p_close_up"] is None
    legacy = outcome({"date": "2099-03-04", "gap_expected": 0.0, "exclude_from_scoring": False})
    assert legacy["p_close_up"] is None and legacy["y_close_up"] == 1


def test_gap_basis_tx_settle_measures_input_error_against_futures_basis():
    call = {"date": "2099-03-04", "gap_expected": 0.005, "exclude_from_scoring": False, "gap_basis": "tx_settle"}
    assert outcome(call)["input_err"] == pytest.approx(0.005 - 0.004)    # 對 night_tx_chg
    old = {k: v for k, v in call.items() if k != "gap_basis"}
    assert outcome(old)["input_err"] == pytest.approx(0.005 - 0.009)     # 舊口徑對 night_spot_gap


def test_compute_prints_unavailable_when_sp_or_history_fails(monkeypatch):
    calls = [{"date": "2099-03-04", "gap_expected": 0.0, "exclude_from_scoring": False}]
    monkeypatch.setattr(vmc, "breadth_at", lambda engine, day: 0.3)
    monkeypatch.setattr(vmc, "vix_prior", lambda engine, day: 18.0)

    def boom(engine):
        raise RuntimeError("db down")
    monkeypatch.setattr(vmc, "sp_series", boom)

    class NoHist(FakeFetcher):
        def history(self, day):
            return None
    logs = []
    rows = vmc.compute(calls, fetcher=NoHist({D: (P, 1000.0, 1002.0, 1015.0)}), engine=object(),
                       today=D, out=logs.append)
    text = "\n".join(logs)
    assert "S&P 基準不可用" in text and "基準歷史不可用" in text
    assert rows[0].get("base_a_p_close_up") is None       # 留空，不是 0


# ---------- 守門：compute 寫入基準、Fetcher.history、口徑分組、block 長度、gap_up 基準 ----------

def test_compute_writes_baseline_fields_into_the_row(monkeypatch):
    calls = [{"date": "2099-03-04", "gap_expected": 0.0, "exclude_from_scoring": False}]
    monkeypatch.setattr(vmc, "breadth_at", lambda engine, day: 0.3)
    monkeypatch.setattr(vmc, "vix_prior", lambda engine, day: 18.0)
    monkeypatch.setattr(vmc, "sp_series", lambda engine: [])
    rows = vmc.compute(calls, fetcher=FakeFetcher({D: (P, 1000.0, 1002.0, 1015.0)}), engine=object(),
                       today=D, out=lambda *_: None)
    assert rows[0]["base_n_close_up"] == 50 and rows[0]["base_a_p_close_up"] == pytest.approx(26 / 52)
    assert rows[0]["base_a_p_gap_up"] is None and rows[0]["base_n_gap_up"] == 0   # gap_up 基準不可用


def test_compute_warns_when_history_is_empty_not_only_none(monkeypatch):
    calls = [{"date": "2099-03-04", "gap_expected": 0.0, "exclude_from_scoring": False}]
    monkeypatch.setattr(vmc, "breadth_at", lambda engine, day: 0.3)
    monkeypatch.setattr(vmc, "vix_prior", lambda engine, day: 18.0)
    monkeypatch.setattr(vmc, "sp_series", lambda engine: [])

    class EmptyHist(FakeFetcher):
        def history(self, day):
            return []
    logs = []
    vmc.compute(calls, fetcher=EmptyHist({D: (P, 1000.0, 1002.0, 1015.0)}), engine=object(), today=D,
                out=logs.append)
    assert any("基準歷史不可用" in x for x in logs)


def bare_fetcher(monkeypatch, data, months=3):
    f = vmc.Fetcher.__new__(vmc.Fetcher)
    f.hist, f.tx_cache, f.notes, f.asked = {}, {}, [], []

    def month(day):
        f.asked.append((day.year, day.month))
        return data.get((day.year, day.month), {})
    f.month = month
    monkeypatch.setattr(vmc, "HIST_MONTHS", months)
    return f


def test_fetcher_history_walks_back_month_by_month_across_the_year_boundary(monkeypatch):
    data = {(2026, 2): {dt.date(2026, 2, 2): (1, 1, 1, 103.0)}, (2026, 1): {dt.date(2026, 1, 30): (1, 1, 1, 102.0)},
            (2025, 12): {dt.date(2025, 12, 31): (1, 1, 1, 100.0)}}
    f = bare_fetcher(monkeypatch, data)
    got = f.history(dt.date(2026, 2, 15))
    assert f.asked == [(2026, 2), (2026, 1), (2025, 12)]
    assert [(h["date"], h["close_up"]) for h in got] == [(dt.date(2026, 1, 30), 1), (dt.date(2026, 2, 2), 1)]


def test_fetcher_history_with_a_missing_month_is_unavailable_not_bridged(monkeypatch):
    # 二月沒資料（含 stat 非 OK 回空 dict）：不能把 1/30 與 3/2 當相鄰交易日
    data = {(2026, 3): {dt.date(2026, 3, 2): (1, 1, 1, 102.0)}, (2026, 1): {dt.date(2026, 1, 30): (1, 1, 1, 100.0)}}
    f = bare_fetcher(monkeypatch, data)
    assert f.history(dt.date(2026, 3, 15)) is None
    assert any("2026-02" in n for n in f.notes)


def block_series():
    return np.repeat([1.0, -1.0, 1.0, -1.0], 10)      # 平均 0、強自相關


def test_block_bootstrap_uses_contiguous_blocks_of_the_requested_length():
    v = block_series()
    w1, w10 = (lambda c: c[1] - c[0])(vmc._cbb_ci(v, block=1)), (lambda c: c[1] - c[0])(vmc._cbb_ci(v, block=10))
    assert w10 > 1.5 * w1 > 0           # block=1 退化成 iid、區間窄；10 日區塊保留自相關、區間寬
    assert vmc._cbb_ci(v, block=40) == (0.0, 0.0)   # 區塊＝整段：只是旋轉，平均不變
    assert vmc._cbb_ci(v[:5], block=10) == vmc._cbb_ci(v[:5], block=5)   # 區塊長度不超過樣本數


def gap_row(day, basis, spot, tx, actual):
    r = outcome({"date": day, "regime": "rotation", "action": "wait", "gap_expected": tx,
                 "exclude_from_scoring": False, "gap_basis": basis})
    r.update(night_spot_gap=spot, night_tx_chg=tx, gap_0905=actual, gap_tx_open=actual, gap_open_official=actual,
             gap_expected=tx)
    return r


def new_basis_rows(n=20):
    # 新口徑：實際＝0.5×夜盤÷結算；night_spot_gap 是無關的另一個序列（實際的 4 倍）
    xs = [0.002 * (1 + i % 4) * (1 if i % 2 else -1) for i in range(n)]
    return [gap_row(f"2099-05-{i + 1:02d}", "tx_settle", 4 * x * 0.5, x, 0.5 * x) for i, x in enumerate(xs)]


def old_basis_rows(n=20):
    xs = [0.003 * (1 + i % 3) * (1 if i % 2 else -1) for i in range(n)]
    return [gap_row(f"2099-04-{i + 1:02d}", None, x, 0.0, 0.2 * x) for i, x in enumerate(xs)]


def test_brief_scaling_ratio_equals_the_grouped_new_basis_value(tmp_path):
    path = tmp_path / "o.jsonl"
    vmc.append_outcomes(path, new_basis_rows())
    logs = []
    vmc.brief(path, out=logs.append)
    text = "\n".join(logs)
    want = vmc.summarize(new_basis_rows(), "gap_0905", raw_key="night_tx_chg")["slope"]
    assert want == pytest.approx(0.5)
    advice = [x for x in logs if x.startswith("→")]
    assert len(advice) == 1 and f"縮放比 {want:.2f} 已有統計支持" in advice[0]
    assert "0.12" not in text           # 舊口徑 raw（night_spot_gap）算出的 0.125 不能出現


def test_brief_never_recommends_scaling_from_old_basis_only(tmp_path):
    path = tmp_path / "o.jsonl"
    vmc.append_outcomes(path, old_basis_rows())
    assert vmc.summarize(old_basis_rows(), "gap_0905")["apply_scaling"]      # 舊口徑自己達標
    logs = []
    vmc.brief(path, out=logs.append)
    advice = [x for x in logs if x.startswith("→")]
    assert len(advice) == 1 and "inconclusive" in advice[0] and "已有統計支持" not in advice[0]


def test_brief_with_mixed_bases_uses_only_the_new_basis_group(tmp_path):
    path = tmp_path / "o.jsonl"
    vmc.append_outcomes(path, old_basis_rows() + new_basis_rows())
    logs = []
    vmc.brief(path, out=logs.append)
    advice = [x for x in logs if x.startswith("→")]
    assert len(advice) == 1 and "縮放比 0.50 已有統計支持" in advice[0]


def test_bark_line_reports_scale_only_for_new_basis_group():
    rows = old_basis_rows() + new_basis_rows()
    text = vmc.bark_line(rows, rows[-1:])
    new_part = [x for x in text.split("\n") if "新口徑" in x][0]
    old_part = [x for x in text.split("\n") if "舊口徑" in x][0]
    assert "縮放比 0.50" in new_part and "縮放比" not in old_part.replace("不給縮放比", "")
    only_new = vmc.bark_line(new_basis_rows(), [])
    assert "縮放比 0.50" in only_new and "0.12" not in only_new


def test_render_summary_keeps_the_two_gap_bases_in_separate_groups():
    logs = []
    vmc.render_summary(old_basis_rows(20) + new_basis_rows(12), logs.append)
    heads = [x for x in logs if x.startswith("[缺口口徑")]
    assert len(heads) == 2 and "舊口徑），20 筆" in heads[0] and "新口徑），12 筆" in heads[1]
    only_old = []
    vmc.render_summary(old_basis_rows(20), only_old.append)
    assert [x for x in only_old if x.startswith("[缺口口徑")] and not any("新口徑）" in x for x in only_old)


def test_gap_up_keeps_direction_baselines_a_c_but_no_probability_and_no_b():
    hist, day = mk_hist([1, 0, 1, 1, 0, 1])
    sp = [(day - dt.timedelta(days=9), 0), (day - dt.timedelta(days=8), 1)]   # (日期, 方向)：前一個 S&P 交易日收漲
    b = vmc.baseline_fields(day, hist, sp)
    assert b["base_n_gap_up"] == 0
    assert all(b[f"base_{k}_p_gap_up"] is None for k in "abc")        # 機率需要 09:05 歷史：不可用
    assert b["base_b_dir_gap_up"] is None                             # (b) 昨日方向需要 09:05 歷史
    assert b["base_a_dir_gap_up"] == 1 and b["base_c_dir_gap_up"] == 1   # (a)(c) 方向不依賴 09:05 歷史
    assert b["base_a_p_close_up"] is not None and b["base_n_oc_up"] == 6    # 其他目標不受影響
    # 空歷史時 (a)(c) 方向照寫
    e = vmc.baseline_fields(day, [], sp)
    assert e["base_a_dir_gap_up"] == 1 and e["base_c_dir_gap_up"] == 1
    # 彙總：機率不採用、(b) 方向不採用（舊列有值也一樣）；(a)(c) 算命中差
    rows = [{"date": f"2099-04-{i + 1:02d}", "p_gap_up": 0.6, "y_gap_up": i % 2, "base_a_p_gap_up": 0.5,
             "base_a_dir_gap_up": 1, "base_b_dir_gap_up": 1, "base_c_dir_gap_up": 0} for i in range(25)]
    s = vmc.prob_summary(rows, "gap_up")["baselines"]
    assert s["a"]["n_brier"] == 0 and s["b"]["n_hit"] == 0 and s["b"]["a_mean"] is None
    assert s["a"]["n_hit"] == 25 and s["a"]["a_mean"] == pytest.approx(0.0)    # 模型恆看漲＝基準 (a)
    assert s["c"]["n_hit"] == 25 and s["c"]["a_mean"] is not None
    logs = []
    vmc.render_prob_summary(rows, logs.append)
    gl = [x for x in logs if "gap_up" in x or "09:05" in x]
    assert any("Brier 不可用（缺 09:05 歷史）" in x and "命中差 ā" in x for x in gl)
    assert any("(b)" in x and "命中差不可用" in x for x in logs[-3:])


# ---------- 多臂配對（fable 臂、等權臂對 claude 臂）----------

def _oc(day, y, p, scorable=True):
    return {"date": day, "scorable": scorable, **{f"y_{t}": y for t in vmc.PROB_TARGETS},
            **{f"p_{t}": p for t in vmc.PROB_TARGETS}}


def _arm(day, p, h="H", **kw):
    return {"date": day, "model_version": "fable", "p_close_up": p, "p_oc_up": p, "p_gap_up": p,
            "input_snapshot_hash": h, "exclude_from_scoring": False, "error": None, **kw}


def _call(day, h="H"):
    return {"date": day, "model_version": "claude", "input_snapshot_hash": h}


def test_arm_report_pairing_equal_weight_and_sign():
    # y=1：claude p=0.6、fable p=0.8、等權 0.7 → d_fable = 0.16-0.04 = +0.12（正＝fable 較好）
    rep = vmc.arm_report([_oc("2099-01-01", 1, 0.6)], [_call("2099-01-01")], [_arm("2099-01-01", 0.8)])
    t = rep["targets"]["close_up"]
    assert t["n"] == 1 and rep["n_dates"] == 1
    assert t["brier_claude"] == pytest.approx(0.16)
    assert t["arms"]["fable"]["brier"] == pytest.approx(0.04)
    assert t["arms"]["fable"]["d_mean"] == pytest.approx(0.12)
    assert t["arms"]["equal_weight"]["brier"] == pytest.approx(0.09)
    assert t["arms"]["equal_weight"]["d_mean"] == pytest.approx(0.07)


def test_equal_weight_needs_both_arms_to_have_a_value():
    arm = _arm("2099-01-01", 0.8, p_oc_up=None)
    rep = vmc.arm_report([_oc("2099-01-01", 1, 0.6)], [_call("2099-01-01")], [arm])
    assert rep["targets"]["oc_up"]["n"] == 0 and "equal_weight" not in rep["targets"]["oc_up"]["arms"]
    assert rep["targets"]["close_up"]["n"] == 1   # 其他目標不受影響
    oc = _oc("2099-01-01", 1, 0.6)
    oc["p_gap_up"] = None                         # claude 缺值：等權與 fable 都不進該目標
    rep = vmc.arm_report([oc], [_call("2099-01-01")], [_arm("2099-01-01", 0.8)])
    assert rep["targets"]["gap_up"]["n"] == 0


def test_arm_report_excludes_and_counts_each_reason():
    days = [f"2099-01-0{i}" for i in range(1, 8)]
    outcomes = [_oc(d, 1, 0.6) for d in days[:6]]          # 第 7 天沒有 outcome
    calls = [_call(d) for d in days]
    calls[3] = _call(days[3], h=None)                      # claude 列缺 hash
    arms = [_arm(days[0], 0.8),
            _arm(days[1], 0.8, h="OTHER"),                 # hash 不一致
            _arm(days[2], 0.8, exclude_from_scoring=True),
            _arm(days[3], 0.8),
            _arm(days[4], 0.8, error="逾時"),
            _arm(days[5], 0.8, exclude_from_scoring=None),  # 未標記不計分
            _arm(days[6], 0.8)]
    rep = vmc.arm_report(outcomes, calls, arms)
    assert rep["n_dates"] == 1
    assert rep["skipped"] == {"arm_rows": 7, "excluded": 2, "error": 1, "no_outcome": 1,
                              "hash_missing": 1, "hash_mismatch": 1}


def test_arm_report_ignores_unscorable_outcomes_and_other_models():
    arm_other = {**_arm("2099-01-01", 0.8), "model_version": "fable_synth"}
    rep = vmc.arm_report([_oc("2099-01-01", 1, 0.6, scorable=False)], [_call("2099-01-01")], [_arm("2099-01-01", 0.8)])
    assert rep["n_dates"] == 0 and rep["skipped"]["no_outcome"] == 1
    assert vmc.arm_report([_oc("2099-01-01", 1, 0.6)], [_call("2099-01-01")], [arm_other])["skipped"]["arm_rows"] == 0


def test_arm_verdict_inconclusive_below_min_n_and_when_ci_crosses_zero():
    days = [f"2099-02-{i:02d}" for i in range(1, 31)]
    outcomes = [_oc(d, 1, 0.5) for d in days]
    calls = [_call(d) for d in days]
    rep = vmc.arm_report(outcomes[:5], calls, [_arm(d, 0.9) for d in days[:5]])
    lines = []
    vmc.render_arm_report(rep, lines.append)
    assert any("inconclusive（n<20）" in x for x in lines)
    rep = vmc.arm_report(outcomes, calls, [_arm(d, 0.9) for d in days])   # 全部都贏 → CI 下界 >0
    assert rep["targets"]["close_up"]["arms"]["fable"]["verdict"] == "該臂優於 claude"
    rnd = np.random.default_rng(3)
    mixed = [_arm(d, 0.9 if rnd.random() < 0.5 else 0.3) for d in days]  # 隨機贏輸、幅度對稱 → 跨零
    out = vmc.arm_report([_oc(d, 1, 0.5) for d in days], calls, mixed)
    assert out["targets"]["close_up"]["arms"]["fable"]["verdict"] == "inconclusive"


def test_arms_section_brief_is_one_line_and_silent_without_arms(tmp_path):
    arms, calls = tmp_path / "arms.jsonl", tmp_path / "calls.jsonl"
    lines = []
    vmc.arms_section([_oc("2099-01-01", 1, 0.6)], calls, arms, lines.append, full=False)
    assert lines == []                                     # 沒檔：不印
    arms.write_text(json.dumps(_arm("2099-01-01", 0.8)) + "\n", encoding="utf-8")
    calls.write_text(json.dumps(_call("2099-01-01")) + "\n", encoding="utf-8")
    vmc.arms_section([_oc("2099-01-01", 1, 0.6)], calls, arms, lines.append, full=False)
    assert len(lines) == 1 and "n=1" in lines[0] and "描述性" in lines[0]
