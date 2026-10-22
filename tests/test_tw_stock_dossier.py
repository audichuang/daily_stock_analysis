"""四維度資料包：財報日期→季度的對應，以及各段缺資料時印「無資料」而不是估算或炸掉。"""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "tw_stock_dossier", Path(__file__).resolve().parents[1] / "scripts" / "tw_stock_dossier.py")
dossier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dossier)


def test_statement_dates_map_to_quarters():
    # 公告截止日：5/15→Q1、8/14→Q2、11/14→Q3、次年 3/31→上一年 Q4
    assert [dossier._quarter_label(d) for d in ("2026-05-15", "2026-08-14", "2025-11-14", "2026-03-31")] == [
        "2026Q1", "2026Q2", "2025Q3", "2025Q4"]


def test_render_with_every_section_missing_says_no_data():
    payload = {"stock_id": "9999", "name": None, "as_of": "2026-08-28",
               "fundamentals": {"monthly_revenue": [], "ttm_revenue_yoy_pct": None, "quarters": []},
               "contract_liabilities": [],
               "chips": {"institutional": None, "margin": None, "holding": None, "branch": None},
               "valuation": None, "smc": None}
    md = dossier.render(payload)
    assert md.count(dossier.NA) >= 6
    assert "沒有單獨列示合約負債" in md


def _hd(rows):
    import pandas as pd
    out = []
    for d, pct in rows:
        out += [{"date": pd.Timestamp(d), "level": 15, "holders": 9, "pct": pct},
                {"date": pd.Timestamp(d), "level": 17, "holders": 60000, "pct": 100.0}]
    return pd.DataFrame(out)


def test_weekly_change_only_between_consecutive_weeks():
    # 10/08 是週四（10/09 國慶前提前），與 10/16 隔 8 天，仍算相鄰週
    assert dossier.holding_summary(_hd([("2026-10-08", 34.27), ("2026-10-16", 33.75)]))[
        "big_holder_pct_wow"] == -0.52
    # 10/09 那週缺：10/02 -> 10/16 隔 14 天，不能標成週變化
    out = dossier.holding_summary(_hd([("2026-10-02", 30.0), ("2026-10-16", 33.75)]))
    assert out["big_holder_pct_wow"] is None and out["big_holder_pct"] == 33.75


def test_holding_summary_empty_is_none():
    import pandas as pd
    assert dossier.holding_summary(pd.DataFrame()) is None
