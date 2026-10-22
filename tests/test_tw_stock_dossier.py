"""四維度資料包：財報日期→季度的對應，以及各段缺資料時印「無資料」而不是估算或炸掉。"""

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.services import tw_stock_dossier as dossier  # noqa: E402


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


def test_stock_name_falls_back_to_index_for_tpex(monkeypatch):
    from src.data import stock_index_loader

    monkeypatch.setattr(dossier.market_repo, "stock_info", lambda sid, engine=None: None)
    monkeypatch.setattr(stock_index_loader, "get_stock_name_index_map", lambda: {"3324.TWO": "雙鴻", "2330.TW": "台積電"})
    assert dossier.stock_name("3324") == "雙鴻"
    assert dossier.stock_name("2330") == "台積電"
    monkeypatch.setattr(dossier.market_repo, "stock_info", lambda sid, engine=None: {"name": "上市名"})
    assert dossier.stock_name("2330") == "上市名"


def test_build_isolates_section_failures(monkeypatch):
    import pandas as pd
    from src.data import stock_index_loader

    monkeypatch.setattr(stock_index_loader, "get_stock_name_index_map", lambda: {"3324.TWO": "雙鴻"})

    def boom(*a, **k):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(dossier, "_sql", lambda engine, sql, **kw: pd.DataFrame({"d": [pd.Timestamp("2026-08-28")]}))
    monkeypatch.setattr(dossier, "stock_name", lambda sid, engine=None: "雙鴻")
    monkeypatch.setattr(dossier, "technicals", boom)
    monkeypatch.setattr(dossier, "fundamentals", boom)
    monkeypatch.setattr(dossier, "valuation", boom)
    monkeypatch.setattr(dossier, "contract_liabilities", lambda *a: [])
    monkeypatch.setattr(dossier, "chips", lambda *a, **k: {"institutional": None, "margin": None,
                                                           "holding": None, "branch": None})
    p = dossier.build("3324.TWO", engine=object())
    assert p["errors"] == ["技術面", "基本面", "估值"]
    assert p["smc"] is None and p["valuation"] is None and p["fundamentals"]["quarters"] == []
    assert "讀取失敗" in dossier.render(p)


def test_build_rejects_wrong_market_suffix(monkeypatch):
    import pandas as pd
    import pytest
    from src.data import stock_index_loader

    monkeypatch.setattr(stock_index_loader, "get_stock_name_index_map",
                        lambda: {"3324.TWO": "雙鴻", "2330.TW": "台積電"})
    with pytest.raises(LookupError, match=r"2330\.TWO 應為 2330\.TW"):
        dossier.build("2330.TWO", engine=object())
    with pytest.raises(LookupError, match=r"3324\.tw 應為 3324\.TWO"):
        dossier.build("3324.tw", engine=object())
    # 正確後綴、索引查無的新掛牌、裸代號都照常往下查 market.price
    seen = []
    monkeypatch.setattr(dossier, "_sql", lambda engine, sql, **kw: seen.append(kw["s"]) or pd.DataFrame({"d": [None]}))
    for code in ("2330.TW", "3324.TWO", "7777.TWO", "2330"):
        with pytest.raises(LookupError, match="查無資料"):
            dossier.build(code, engine=object())
    assert seen == ["2330", "3324", "7777", "2330"]


def test_holding_summary_tolerates_missing_holder_count():
    # 最新一週 level 17 的股東數是空值：只讓這一欄變 None，不能 int(NaN) 把整段籌碼弄成「無資料」
    import pandas as pd

    from src.services.tw_stock_dossier import holding_summary

    hd = pd.DataFrame([
        {"date": "2026-10-09", "level": 15, "pct": 50.0, "holders": 10},
        {"date": "2026-10-09", "level": 17, "pct": 100.0, "holders": 9000},
        {"date": "2026-10-16", "level": 15, "pct": 51.0, "holders": 10},
        {"date": "2026-10-16", "level": 17, "pct": 100.0, "holders": None},
    ])
    s = holding_summary(hd)
    assert s["big_holder_pct"] == 51.0 and s["big_holder_pct_wow"] == 1.0
    assert s["total_holders"] is None


@pytest.mark.parametrize("gap,expected", [(False, 100.0), (True, None)])
def test_ttm_revenue_yoy_needs_24_consecutive_months(monkeypatch, gap, expected):
    # 中間缺一個月時最近 24 列跨了 25 個月，兩個 12 列窗口錯開，不能標成「近 12 個月年增」
    import pandas as pd

    from src.services import tw_stock_dossier as dossier

    months = pd.period_range("2024-10", "2026-09", freq="M").to_timestamp()
    if gap:
        months = pd.period_range("2024-09", "2026-09", freq="M").to_timestamp().delete(12)
    rev = pd.DataFrame({"revenue_month": months[::-1], "revenue": [200 if i < 12 else 100 for i in range(24)],
                        "yoy": None, "announce_date": None})

    def fake_sql(engine, sql, **kw):
        return rev if "monthly_revenue" in sql else pd.DataFrame(columns=["date", "account", "value"])

    monkeypatch.setattr(dossier, "_sql", fake_sql)
    assert dossier.fundamentals(None, "9999", "2026-10-22")["ttm_revenue_yoy_pct"] == expected
