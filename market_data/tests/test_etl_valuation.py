import json
from pathlib import Path

from market_data import etl

FIX = Path(__file__).parent / "fixtures"


def test_transform_valuation_parses_roc_date_and_blanks():
    rows = json.loads((FIX / "bwibbu.json").read_bytes())
    df = etl.transform_valuation(rows)
    assert df.index.names == ["stock_id", "date"]
    r = df.loc[("1101", df.index.get_level_values("date")[0])]
    assert float(r["dividend_yield"]) == 3.38
    assert float(r["pb_ratio"]) == 0.75
    # 台泥 PEratio was blank "" -> NaN, not 0
    assert r["pe_ratio"] != r["pe_ratio"]  # NaN
    # ROC 1150703 -> 2026-07-03
    assert str(df.index.get_level_values("date")[0])[:10] == "2026-07-03"


def test_transform_index_maps_taiex():
    rows = json.loads((FIX / "fmtqik.json").read_bytes())
    df = etl.transform_index(rows)
    assert df.index.names == ["index_id", "date"]
    last = df.xs("TAIEX", level="index_id").iloc[-1]
    assert float(last["close"]) == 46780.62
    assert float(last["change"]) == 36.46
    assert int(last["turnover"]) == 1078028137102


def test_parse_valuation_day_locates_columns_by_name():
    """欄位順序隨年代變（2015 五欄、2026 八欄且殖利率排在本益比前），靠 fields 定位。"""
    from datetime import date

    from market_data import sources

    payload = {"fields": ["證券代號", "證券名稱", "殖利率(%)", "股利年度",
                          "本益比", "股價淨值比", "財報年/季"],
               "data": [["2330", "台積電", "1.50", "114", "20.10", "5.50", "115/1"],
                        ["1101", "台泥", "3.38", "114", "-", "0.75", "115/1"]]}
    df = sources.parse_valuation_day(payload, date(2026, 7, 24))
    assert float(df.loc[("2330", "2026-07-24"), "pe_ratio"]) == 20.10
    assert float(df.loc[("2330", "2026-07-24"), "pb_ratio"]) == 5.50
    pe = df.loc[("1101", "2026-07-24"), "pe_ratio"]
    assert pe != pe          # "-" -> NaN(進 DB 為 NULL),不是 0


def test_parse_valuation_day_rejects_schema_without_valuation_columns():
    """三個估值欄全消失時不能回全 NULL 列——upsert 不 coalesce,會洗掉既有值。"""
    from datetime import date

    import pytest

    from market_data import sources

    payload = {"fields": ["證券代號", "證券名稱"], "data": [["2330", "台積電"]]}
    with pytest.raises(ValueError, match="估值欄全部消失"):
        sources.parse_valuation_day(payload, date(2026, 7, 24))


def test_parse_tpex_ex_dividend_official_reference_price():
    """上櫃除權息官方值：民國斜線日期 + 靠 fields 定位（欄位共 21 個，順序不可硬編）。"""
    import json

    from market_data import sources

    payload = json.loads((FIX / "tpex_exdailyq.json").read_text(encoding="utf-8"))
    df = sources.parse_tpex_ex_dividend(payload)
    r = df[df["stock_id"] == "5324"].iloc[0]
    assert str(r["date"])[:10] == "2020-01-02"        # 109/01/02
    assert float(r["close_before"]) == 9.80
    assert float(r["reference_price"]) == 9.73
    # 代號欄要 strip（名稱欄有大量全角補空白）
    assert all(s == s.strip() for s in df["stock_id"])


def test_parse_company_monthly_revenue_picks_monthly_not_cumulative_yoy():
    """MOPS 個別公司頁是**轉置**表格，且有兩個「增減百分比」——第一個是本月、第二個是累計。

    存在的理由是存活偏誤：彙總報表 `t21sc03` 只列目前仍在申報的公司，實測 2020-06 那份
    979 家裡完全沒有 6452 康友（當時仍在交易，同年 8 月才停止）。
    """
    from market_data import sources

    html = (FIX.parent / "fixtures" / "mops_company_revenue.html").read_text(
        encoding="utf-8", errors="replace")
    rec, reason = sources.parse_company_monthly_revenue(html, "6452", 2020, 6)
    assert reason == "ok"
    assert rec["revenue"] == 382561.0
    assert rec["yoy"] == -11.43           # 本月 YoY，不是累計的 -5.25
    assert str(rec["revenue_month"])[:10] == "2020-06-01"
    assert str(rec["announce_date"])[:10] == "2020-07-10"   # 法定申報期限=次月 10 日


def test_parse_company_monthly_revenue_rejects_month_mismatch():
    """回應頁的年月要核對——直接拿呼叫參數當 PK，MOPS 回舊頁就會用錯月份污染 DB。

    這一版之前的測試正好證明了漏洞：它用顯示「民國109年06月」的 fixture 以 (2020, 12)
    呼叫，並期待寫成 2020-12。獨立審查抓出。
    """
    from market_data import sources

    html = (FIX.parent / "fixtures" / "mops_company_revenue.html").read_text(
        encoding="utf-8", errors="replace")
    rec, reason = sources.parse_company_monthly_revenue(html, "6452", 2020, 12)
    assert rec is None
    assert reason.startswith("month_mismatch")


def test_parse_company_monthly_revenue_distinguishes_failure_reasons():
    """四種失敗必須分開：混成同一個 None 會讓 HTTP 失敗被誤判成「這家公司補不回來」，
    整檔剩餘月份全部跳過，而「補不回的公司數」正是存活偏誤殘餘量的分母。"""
    from market_data import sources

    dead = (FIX.parent / "fixtures" / "mops_company_revenue_delisted.html").read_text(
        encoding="utf-8", errors="replace")
    assert sources.parse_company_monthly_revenue(dead, "2448", 2020, 6) == (None, "not_public")
    assert sources.parse_company_monthly_revenue(
        "外國發行人免申報本項資訊", "1592", 2020, 6) == (None, "foreign_exempt")
    _, r = sources.parse_company_monthly_revenue("<html>民國109年06月</html>", "6452", 2020, 6)
    assert r in ("no_data", "parse_failed")


def test_terminal_reasons_are_only_the_two_hard_boundaries():
    """HTTP／解析／月份不符都要可重試，不能讓它們放棄整檔公司。"""
    from market_data import crawl

    assert crawl._TERMINAL_REASONS == ("not_public", "foreign_exempt")
    for r in ("http_failed", "parse_failed", "no_data", "month_mismatch(...)"):
        assert r not in crawl._TERMINAL_REASONS
