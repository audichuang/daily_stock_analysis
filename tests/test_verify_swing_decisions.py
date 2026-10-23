# -*- coding: utf-8 -*-
"""Tests for scripts/verify_swing_decisions.py（不碰 DB／網路）。

回驗的兩個致命點：持有窗口有沒有跟量測腳本逐格對齊（差一天，Brier 與加值都對不上），
以及未到期的決策有沒有被誤當成已到期（那會用不足 60 天的報酬評分）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verify_swing_decisions import (  # noqa: E402
    _ma_check, _portfolio_signals, fill_ok, read_log, realized_return, selection_lift_ci, summarize,
    window,
)

CAL = pd.bdate_range("2026-01-05", periods=30)      # 週一起算的營業日


def test_window_is_next_open_to_the_hth_trading_day_close():
    entry, exit_, left = window(CAL, "2026-01-05", 5)
    assert entry == CAL[1] and exit_ == CAL[5] and left == 0


def test_decision_made_on_a_non_trading_day_aligns_backwards():
    """判斷常在週末／收盤後做——要對齊到最近的**過去**交易日，不能借用未來那一天的開盤。"""
    sat = pd.Timestamp("2026-01-10")                 # 週六
    assert window(CAL, sat, 5)[0] == window(CAL, CAL[4], 5)[0]   # 對齊到 1/9 週五


def test_pending_decision_reports_remaining_days_instead_of_a_fake_return():
    entry, exit_, left = window(CAL, CAL[27], 5)
    assert entry is None and exit_ is None and left == 3


def test_read_log_skips_blank_and_comment_lines(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('# 註解\n\n{"date":"2026-07-24","stock_id":"2615","verdict":"enter"}\n',
                 encoding="utf-8")
    df = read_log(p)
    assert len(df) == 1 and df["stock_id"].iloc[0] == "2615"


def test_read_log_drops_closure_and_weekend_rows_and_counts_them(tmp_path, monkeypatch):
    closed = tmp_path / "closed.txt"
    closed.write_text("2026-10-23  # typhoon\n", encoding="utf-8")
    monkeypatch.setenv("TW_ADHOC_CLOSED_FILE", str(closed))
    p = tmp_path / "d.jsonl"
    rows = ["2026-10-22", "2026-10-23", "2026-10-24"]  # open, adhoc closed, Saturday
    p.write_text("".join(f'{{"date":"{d}","stock_id":"2615","verdict":"pass"}}\n' for d in rows),
                 encoding="utf-8")
    df = read_log(p)
    assert list(df["date"]) == ["2026-10-22"] and df.attrs["closed_excluded"] == 2
    assert len(read_log(p, drop_closed=False)) == 3


def test_read_log_refuses_a_truncated_line_instead_of_dropping_it(tmp_path):
    """一行壞掉就整份不算——靜默跳過等於讓回驗少掉幾筆而沒人知道。"""
    p = tmp_path / "d.jsonl"
    p.write_text('{"date":"2026-07-24","stock_id":"2615"\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="不是合法 JSON"):
        read_log(p)


def test_entry_waits_for_decided_at_not_just_the_signal_date():
    """週五的訊號若到週一晚上才研究完，不能用週一開盤成交——那天的判斷還不存在。

    `decided_at` 就是為了讓這件事可稽核才要求必填；忽略它會讓回驗數字含未來資訊。
    """
    fri, mon, tue = CAL[4], CAL[5], CAL[6]
    naive = window(CAL, fri, 5)[0]
    late = window(CAL, fri, 5, decided_at="2026-01-12T21:30+08:00")[0]   # 週一晚間
    assert naive == mon          # 只看訊號日 → 週一進場
    assert late == tue            # 看判斷時點 → 週二才合法


def test_decided_at_before_the_signal_date_does_not_pull_entry_earlier():
    assert window(CAL, CAL[4], 5, decided_at="2025-12-01T09:00+08:00")[0] == CAL[5]


def test_gap_through_the_entry_range_is_a_no_fill():
    """開盤已高於建議區間上界＝這筆沒成交；算成成交就是把沒發生的決策計進加值統計。"""
    assert not fill_ok(95.0, [85.0, 88.0])
    assert fill_ok(88.0, [85.0, 88.0])
    assert fill_ok(80.0, [85.0, 88.0])       # 更便宜仍算成交
    assert fill_ok(999.0, None)              # 沒填區間就不判定


def test_realized_return_uses_exact_cashflows():
    from tw_trade_costs import round_trip_return

    expected = round_trip_return(100.0, 110.0, entry_notional=200_000)
    assert realized_return(100.0, 110.0) == pytest.approx(expected)


def test_selection_lift_identical_arms_is_exactly_zero():
    events = pd.DataFrame({
        "entry_date": CAL[:20],
        "verdict": ["enter"] * 20,
        "r": [0.01, -0.02] * 10,
    })
    assert selection_lift_ci(events, CAL, n=200, block=5, seed=7) == (0.0, 0.0)


def test_selection_lift_does_not_treat_missing_as_zero():
    events = pd.DataFrame({
        "entry_date": [CAL[0], CAL[10]],
        "verdict": ["enter", "pass"],
        "r": [float("nan"), 0.2],
    })
    assert selection_lift_ci(events, CAL, n=100, block=5, seed=7) is None


def test_summarize_counts_the_tails():
    r = pd.Series([0.5, 0.1, -0.25, -0.05])
    s = summarize(r, "enter")
    assert s["筆數"] == 4 and s["勝率"] == "50.0%"
    assert s["P(≥30%)"] == "25.0%" and s["P(≤-20%)"] == "25.0%"


def _panel(closes, stock_id="6166"):
    return pd.DataFrame({stock_id: closes},
                        index=pd.bdate_range("2026-05-01", periods=len(closes)))


def test_ma_check_flags_when_the_logged_threshold_flips_the_verdict():
    """真實案例：6166 收 137.0，照日誌的 `MA10(136.7)` 看是未跌破，但當天 MA10 已漂到
    138.70——其實**已經跌破**。日誌裡的數字是快照，比對一律要用重算值。

    刻意給 11 根、最舊那根是離群值：只餵剛好 n 根的話，「用全部列」或「用 n+1 列」的
    實作也會通過，測不出視窗長度。
    """
    # 最舊 999 應被排除；其後 9 根 140、最後一根 137 → MA10 = (140*9 + 137)/10 = 139.7
    lines = _ma_check(_panel([999.0] + [140.0] * 9 + [137.0]), "6166", "或跌破MA10(136.7)")
    assert len(lines) == 1
    assert "MA10 現在 139.70" in lines[0] and "日誌寫的是 136.70" in lines[0]
    assert "**已跌破**" in lines[0]
    assert "照日誌裡的舊值會判成相反結論" in lines[0]


def test_ma_check_skips_non_trading_gaps_rather_than_counting_them():
    """面板 index 是多檔股票的**聯集**交易日，某檔停牌那天是 NaN；那一列不能佔掉視窗名額。

    6166 有剛好 10 根真實報價（100、140×8、137），倒數第二個聯集日停牌：
    正確答案是 10 根真實的均值 `(100 + 140×8 + 137)/10 = 135.70`。把 NaN 當一列處理
    （或補值）會丟掉最舊的離群值 100、得到 139.70，現價 137 也從「未跌破」翻成「已跌破」。
    """
    closes = [100.0] + [140.0] * 8 + [float("nan")] + [137.0]
    lines = _ma_check(_panel(closes), "6166", "跌破MA10(136.7)")
    assert "MA10 現在 135.70" in lines[0], f"NaN 那列被算進視窗了：{lines[0]}"
    assert "未跌破" in lines[0] and "**已跌破**" not in lines[0]


def test_adj_close_panel_does_not_forward_fill(monkeypatch):
    """`_adj_close_panel` **不得** ffill——這是上一條測不到的那一半。

    `_ma_check` 收到的面板若已被補值，它就再也分不出哪根是真實 K 棒（NaN 已經沒了），
    最後 n 列會混進合成值並把最舊的真實那根推出視窗。所以「不補值」是這支函式的契約，
    要在這裡釘住，不能只靠 `_ma_check` 的測試（那邊餵的面板是自己造的，永遠不含 ffill）。
    """
    import verify_swing_decisions as vsd

    days = pd.to_datetime(["2026-07-24", "2026-07-27", "2026-07-28"])
    raw = pd.DataFrame({                       # 6166 在 07-27 停牌，該格沒有列
        "stock_id": ["2615", "2615", "2615", "6166", "6166"],
        "date": [days[0], days[1], days[2], days[0], days[2]],
        "close": [84.0, 83.0, 83.6, 150.0, 137.0],
    })

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Eng:
        def connect(self): return _Conn()

    monkeypatch.setattr(vsd.pd, "read_sql", lambda *a, **k: raw)
    monkeypatch.setattr(vsd, "load_factors",
                        lambda eng, idx, cols: pd.DataFrame(1.0, index=idx, columns=cols))

    panel = vsd._adj_close_panel(_Eng(), ["2615", "6166"])
    assert pd.isna(panel.loc[days[1], "6166"]), "停牌那格被 ffill 補成合成 K 棒了"
    # 但「現價」仍要拿得到最後一個有效報價（等價於原本的 ffill 語意）
    from verify_swing_decisions import _last_close
    assert _last_close(panel) == {"2615": 83.6, "6166": 137.0}


def test_ma_check_reads_thousands_separators_and_skips_ema():
    """`MA20(1,234.5)` 少了千分位處理只會匹配到裸 `MA20`，靜默丟掉門檻與翻轉警告；
    而 `EMA10` 是另一種均線，被讀成 `MA10` 等於換了條件還宣稱驗過。"""
    lines = _ma_check(_panel([1000.0] * 20, "2330"), "2330", "跌破MA20(1,234.5)")
    assert "日誌寫的是 1234.50" in lines[0]
    assert "照日誌裡的舊值會判成相反結論" in lines[0]   # 現價 1000 < 1234.5 但 > MA20 1000
    assert _ma_check(_panel([140.0] * 10), "6166", "跌破EMA10(136.7)") == []


def test_ma_check_stays_quiet_when_old_and_new_agree():
    """舊值與重算值得到同一個結論時不加警告——每筆都喊狼來了就沒人看了。"""
    lines = _ma_check(_panel([80.0] * 19 + [83.6], "2615"), "2615", "跌破MA20(79.85)")
    assert "未跌破" in lines[0] and "相反結論" not in lines[0]


def test_ma_check_only_touches_moving_averages():
    """SCFI／法人／費半這些要外部資料或人工判斷，不能假裝驗過——印成「未觸發」比不印更糟。"""
    assert _ma_check(_panel([80.0] * 20, "2615"), "2615",
                     "SCFI連續第三週下跌、法人買超中斷轉賣超") == []


def test_ma_check_reports_insufficient_history_instead_of_a_short_window_mean():
    """歷史不足 n 根時要說不足，不能拿 3 根的均值冒充 MA60（會給出一個看似合理的錯門檻）。"""
    lines = _ma_check(_panel([100.0, 101.0, 99.0]), "6166", "跌破MA60(95)")
    assert len(lines) == 1 and "不足以重算" in lines[0]


def test_ma_check_handles_a_bare_ma_reference_and_missing_stock():
    lines = _ma_check(_panel([100.0] * 10), "6166", "跌破MA10")
    assert "MA10 現在 100.00" in lines[0] and "日誌寫的是" not in lines[0]
    assert _ma_check(_panel([100.0] * 10), "9999", "跌破MA10") == []
    assert _ma_check(None, "6166", "跌破MA10") == []


# --- 可成交口徑（組合臂）：進場日與 conf 鍵要跟逐筆路徑一致 -------------------------------

IDX = pd.bdate_range("2026-07-20", periods=12)


def _dec(date, sid, entry_date, conf=None, verdict="enter"):
    return {"date": date, "stock_id": sid, "verdict": verdict,
            "entry_date": entry_date, "confidence": conf}


def test_portfolio_signal_day_is_the_trading_day_before_entry_not_the_log_date():
    """2408 形狀：判斷在 `date` 後的交易日上午才做完，逐筆路徑（`window`）的進場日是再下一日。

    組合臂若仍以 `r['date']` 當訊號日，`simulate` 會在 date 的次一日開盤買進——那天判斷還不
    存在（實例：2408 08-14 09:40 才決定，卻用 08-14 開盤 532 買進，高於區間上界 525）。
    """
    date, decided_day = IDX[3], IDX[4]
    e_d, _, _ = window(IDX, date, 3, decided_at=f"{decided_day.date()}T09:40+08:00")
    assert e_d == IDX[5]                                   # 逐筆路徑：決定日的次一交易日
    sig, _, skipped = _portfolio_signals(pd.DataFrame([_dec(date, "2408", e_d)]), IDX)
    assert skipped == 0
    assert sig.at[decided_day, "2408"]                     # 訊號日 = 決定日，simulate 於 e_d 開盤買
    assert not sig.at[date, "2408"]                        # 不是 r['date']
    assert int(sig.to_numpy().sum()) == 1                  # 沒有往前多移（overdo 守門）


def test_portfolio_conf_is_keyed_by_the_new_signal_day_so_ranking_survives():
    rows = pd.DataFrame([_dec(IDX[3], "1101", IDX[5], conf=0.35),
                         _dec(IDX[4], "2002", IDX[5], conf=0.55),
                         _dec(IDX[3], "3008", IDX[5], conf=None)])
    _, conf, _ = _portfolio_signals(rows, IDX)
    assert conf[(IDX[4], "1101")] == pytest.approx(0.35)
    assert conf[(IDX[4], "2002")] == pytest.approx(0.55)
    assert conf[(IDX[4], "3008")] == 0.0                   # 缺值 → 0，不是 NaN（NaN 會讓排序失真）
    assert (IDX[3], "1101") not in conf                    # 舊鍵（r['date']）查不到


def test_portfolio_entry_on_the_first_index_day_is_skipped_and_counted():
    rows = pd.DataFrame([_dec(IDX[0], "1101", IDX[0], conf=0.3),
                         _dec(IDX[2], "2002", IDX[4], conf=0.3)])
    sig, conf, skipped = _portfolio_signals(rows, IDX)
    assert skipped == 1
    assert not sig["1101"].any() and (IDX[0], "1101") not in conf
    assert sig.at[IDX[3], "2002"]


def test_portfolio_entry_date_missing_or_outside_index_is_skipped_not_raised():
    rows = pd.DataFrame([_dec(IDX[2], "1101", pd.Timestamp("2026-09-01")),
                         _dec(IDX[2], "2002", pd.NaT),
                         _dec(IDX[2], "3008", IDX[4], conf=0.3)])
    sig, _, skipped = _portfolio_signals(rows, IDX)
    assert skipped == 2
    assert int(sig.to_numpy().sum()) == 1 and sig.at[IDX[3], "3008"]


class _Conn:
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, *a, **k):
        class _R:
            @staticmethod
            def fetchall():
                return [(d,) for d in IDX]
        return _R()


class _Eng:
    def connect(self): return _Conn()


def _price_long(opens, closes=None):
    """opens: {sid: [open per IDX day]}；收盤預設等於開盤。"""
    closes = closes or opens
    return pd.DataFrame([
        {"stock_id": sid, "date": d, "open": opens[sid][i], "close": closes[sid][i]}
        for sid in opens for i, d in enumerate(IDX)])


def test_realized_fill_uses_the_unadjusted_open_but_returns_use_adjusted_prices(monkeypatch):
    """除權息後還原開盤 94.5 低於上界 100，但當天名目開盤 105 其實沒成交。

    `entry_range` 是判斷當下的名目價；拿還原價去比會把沒發生的成交算進統計。報酬仍須走前復權。
    """
    import verify_swing_decisions as vsd

    n = len(IDX)
    opens = {"1101": [105.0] * n, "2002": [99.0] * n}      # 1101 名目高於上界；2002 在區間內
    monkeypatch.setattr(vsd.pd, "read_sql", lambda *a, **k: _price_long(opens))
    monkeypatch.setattr(vsd, "load_factors",
                        lambda eng, idx, cols: pd.DataFrame(0.9, index=idx, columns=cols))
    df = pd.DataFrame([
        {"date": IDX[1], "stock_id": "1101", "verdict": "enter", "entry_range": [95, 100]},
        {"date": IDX[1], "stock_id": "2002", "verdict": "enter", "entry_range": [95, 100]},
    ])
    out = vsd.realized(_Eng(), df, 3).set_index("stock_id")
    assert bool(out.at["1101", "no_fill"]) and out.at["1101", "entry_px"] == pytest.approx(105.0)
    assert not bool(out.at["2002", "no_fill"]) and not bool(out.at["2002", "pending"])
    # 收盤與開盤同為 99 × 0.9 → 前復權進出價相同，報酬 = 兩端成本；用名目進場價會多出 10%
    assert out.at["2002", "r"] == pytest.approx(vsd.realized_return(89.1, 89.1))


def test_paired_portfolio_enters_on_the_per_event_entry_day_and_ranks_by_confidence(monkeypatch):
    """端到端接線：進場日 = 逐筆的 entry_date；同日搶一個空位時 confidence 高者勝。"""
    import verify_swing_decisions as vsd

    flat = {sid: [100.0] * len(IDX) for sid in ("1101", "2002")}
    monkeypatch.setattr(vsd.pd, "read_sql", lambda *a, **k: _price_long(flat))
    monkeypatch.setattr(vsd, "load_factors",
                        lambda eng, idx, cols: pd.DataFrame(1.0, index=idx, columns=cols))
    df = pd.DataFrame([_dec(IDX[3], "1101", IDX[5], conf=0.2),      # 字母序在前、信心低
                       _dec(IDX[4], "2002", IDX[5], conf=0.9)])
    _, trades = vsd.paired_portfolio(df, _Eng(), 3, 1)["只收 enter"]
    assert list(trades["stock_id"]) == ["2002"]
    assert trades["entry_date"].iloc[0] == IDX[5]


def _write_log(p, dates):
    p.write_text("".join(f'{{"date":"{d}","stock_id":"2615","verdict":"pass"}}\n' for d in dates),
                 encoding="utf-8")


def test_read_log_excludes_1023_from_the_tracked_list_when_the_local_list_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("TW_ADHOC_CLOSED_FILE", str(tmp_path / "absent.txt"))
    p = tmp_path / "morning.jsonl"
    _write_log(p, ["2026-10-22", "2026-10-23"])
    df = read_log(p)
    assert list(df["date"]) == ["2026-10-22"] and df.attrs["closed_excluded"] == 1


def test_main_always_reports_the_excluded_count(tmp_path, monkeypatch, capsys):
    import verify_swing_decisions as v
    monkeypatch.setenv("TW_ADHOC_CLOSED_FILE", str(tmp_path / "absent.txt"))
    monkeypatch.setenv("STORAGE_DATABASE_URL", "")

    def boom():
        raise RuntimeError("stop after the header")
    monkeypatch.setattr(v, "get_engine", boom)
    cases = {"none": (["2026-10-22"], "已排除 0 筆"),
             "partial": (["2026-10-22", "2026-10-23"], "已排除 1 筆"),
             "all": (["2026-10-23", "2026-10-24"], "全數 2 筆皆為休市日")}
    for name, (dates, expect) in cases.items():
        p = tmp_path / f"{name}.jsonl"
        _write_log(p, dates)
        try:
            v.main(["--log", str(p)])
        except Exception:
            pass
        out = capsys.readouterr().out
        assert expect in out, (name, out)
        assert "是空的" not in out
