# -*- coding: utf-8 -*-
"""財報契約：單位、幣別、YTD 差分、資本支出正負號、金融業科目與 SEC 解析。"""
from __future__ import annotations

from datetime import date

import pytest

from src.services import stock_financials as sf
from src.services import us_financials as us


def _row(d, sheet, account, value):
    return (d, sheet, account, value)


def _tw_rows():
    """以固定年份的三季資料，累計與單季數字刻意不同，算錯就看得出來。"""
    q1, q2, q3 = date(2099, 5, 15), date(2099, 8, 14), date(2099, 11, 14)
    rows = []
    for d, revenue, cum in ((q1, 100, 100), (q2, 110, 210), (q3, 120, 330)):
        rows += [_row(d, "income_sheet", "營業收入合計", revenue),
                 _row(d, "income_sheet_cumulate", "累計營業收入合計", cum),
                 _row(d, "income_sheet", "營業毛利（毛損）", revenue / 2),
                 _row(d, "income_sheet", "母公司業主（淨利／損）", 10),
                 _row(d, "income_sheet", "基本每股盈餘合計", 1.5),
                 _row(d, "balance_sheet", "資產總計", 1000), _row(d, "balance_sheet", "負債總計", 400)]
    rows += [_row(q1, "cash_flows", "營業活動之淨現金流入（流出）", 50),
             _row(q2, "cash_flows", "營業活動之淨現金流入（流出）", 80),
             _row(q3, "cash_flows", "營業活動之淨現金流入（流出）", 150),
             _row(q1, "cash_flows", "取得不動產、廠房及設備", -20),
             _row(q2, "cash_flows", "取得不動產、廠房及設備", -35),
             _row(q3, "cash_flows", "取得不動產、廠房及設備", -70)]
    return rows


def _by_key(rows):
    return {row["key"]: row for row in rows}


def test_tw_amounts_are_scaled_from_thousands_to_one_dollar():
    periods = _by_key(sf.tw_periods_from_rows(_tw_rows(), financial=False))
    assert periods["2099Q1"]["raw"]["revenue"] == 100_000
    assert periods["2099Q1"]["raw"]["assets"] == 1_000_000


def test_tw_eps_is_not_scaled():
    periods = _by_key(sf.tw_periods_from_rows(_tw_rows(), financial=False))
    assert periods["2099Q2"]["raw"]["eps"] == 1.5


def test_tw_cash_flow_is_differenced_from_year_to_date():
    periods = _by_key(sf.tw_periods_from_rows(_tw_rows(), financial=False))
    assert periods["2099Q1"]["raw"]["ocf"] == 50_000
    assert periods["2099Q2"]["raw"]["ocf"] == 30_000
    assert periods["2099Q3"]["raw"]["ocf"] == 70_000
    assert "ocf" in periods["2099Q2"]["derived"] and "ocf" not in periods["2099Q1"]["derived"]


def test_tw_capex_is_positive_and_free_cash_flow_subtracts_it():
    rows = sf.tw_periods_from_rows(_tw_rows(), financial=False)
    assert _by_key(rows)["2099Q2"]["raw"]["capex"] == 15_000
    assert sf._metric_value("free_cash_flow", rows, 1)[0] == 15_000


def test_tw_missing_previous_quarter_leaves_cash_flow_blank_rather_than_ytd():
    rows = [r for r in _tw_rows() if r[0] != date(2099, 8, 14)]
    periods = _by_key(sf.tw_periods_from_rows(rows, financial=False))
    assert periods["2099Q3"]["raw"]["ocf"] is None
    assert periods["2099Q3"]["raw"]["capex"] is None


def test_tw_q4_statement_date_belongs_to_previous_year():
    rows = [_row(date(2099, 3, 31), "income_sheet", "營業收入合計", 5)]
    period = sf.tw_periods_from_rows(rows, financial=False)[0]
    assert period["key"] == "2098Q4" and period["period_end"] == "2098-12-31"
    assert period["announce_date"] == "2099-03-31" and period["announce_date_kind"] == "statutory_deadline"


def test_tw_income_falls_back_to_cumulative_difference_and_marks_it():
    d1, d2 = date(2099, 5, 15), date(2099, 8, 14)
    rows = [_row(d1, "income_sheet_cumulate", "累計營業收入合計", 100),
            _row(d2, "income_sheet_cumulate", "累計營業收入合計", 250)]
    periods = _by_key(sf.tw_periods_from_rows(rows, financial=False))
    assert periods["2099Q2"]["raw"]["revenue"] == 150_000
    assert "revenue" in periods["2099Q2"]["derived"]
    assert "revenue" not in periods["2099Q1"]["derived"]


def test_tw_financial_net_income_never_reads_comprehensive_parent_row():
    """2881 實測：「母公司業主」312 億其實是綜合損益，本期淨利才是 64 億。"""
    d = date(2099, 8, 14)
    rows = [_row(d, "income_sheet", "母公司業主", 312), _row(d, "income_sheet", "本期淨利（淨損）", 64),
            _row(d, "income_sheet", "淨收益", 106)]
    raw = sf.tw_periods_from_rows(rows, financial=True)[0]["raw"]
    assert raw["net_income"] == 64_000
    assert raw["net_revenue"] == 106_000 and raw["revenue"] is None


def test_tw_minority_note_only_when_net_income_falls_back():
    d = date(2099, 8, 14)
    fallback = [_row(d, "income_sheet", "本期淨利（淨損）", 64), _row(d, "income_sheet", "基本每股盈餘合計", 1)]
    parent = fallback + [_row(d, "income_sheet", "母公司業主（淨利／損）", 60)]
    note = "含非控制權益"
    for rows, expected in ((fallback, True), (parent, False)):
        payload = sf._base_payload("TEST.TW", "tw")
        payload["currency"] = "TWD"
        sf._assemble(payload, sf.tw_periods_from_rows(rows, financial=False), financial=False)
        assert any(note in text for text in payload["limitations"]) is expected


def test_tw_contract_liabilities_exclude_insurance_accounts():
    d = date(2099, 8, 14)
    rows = [_row(d, "balance_sheet", "合約負債－流動", 7), _row(d, "balance_sheet", "合約負債－非流動", 3),
            _row(d, "balance_sheet", "保險合約負債", 4771)]
    assert sf.tw_periods_from_rows(rows, financial=False)[0]["raw"]["contract"] == 10_000


def test_tw_financial_deadline_is_later_than_general():
    assert sf._tw_deadline(2099, 1, True) == date(2099, 5, 30)
    assert sf._tw_deadline(2099, 1, False) == date(2099, 5, 15)
    assert sf._tw_deadline(2099, 2, True) == date(2099, 8, 31)


def _assembled(financial=False):
    payload = sf._base_payload("TEST.TW", "tw")
    payload["currency"] = "TWD"
    sf._assemble(payload, sf.tw_periods_from_rows(_tw_rows(), financial=financial), financial=financial)
    return payload


def test_general_template_exposes_only_metrics_with_values_and_explains_missing():
    payload = _assembled()
    keys = {metric["key"] for metric in payload["metrics"]}
    assert {"revenue", "gross_margin", "operating_cash_flow", "capex", "free_cash_flow", "debt_ratio"} <= keys
    assert "contract_liabilities" not in keys
    assert any(item["key"] == "contract_liabilities" for item in payload["not_applicable"])
    assert payload["status"] == "ok"


def test_financial_template_hides_non_applicable_metrics_with_reason():
    payload = _assembled(financial=True)
    keys = {metric["key"] for metric in payload["metrics"]}
    assert not keys & {"gross_margin", "debt_ratio", "operating_cash_flow", "capex", "free_cash_flow"}
    assert {item["key"] for item in payload["not_applicable"]} >= {"gross_margin", "debt_ratio"}
    assert payload["template"] == "financial"


def test_change_handles_zero_negative_base_and_ratio():
    assert sf._change(110, 100, "amount") == 10
    assert sf._change(5, -2, "amount") is None
    assert sf._change(5, 0, "amount") is None
    assert sf._change(0, 10, "amount") == -100
    assert sf._change(60, 55.5, "ratio") == 4.5


def test_prior_year_is_matched_by_period_end_not_label():
    rows = [{"key": "X1", "period_end": "2098-06-30"}, {"key": "X2", "period_end": "2099-03-31"},
            {"key": "X3", "period_end": "2099-06-30"}]
    assert sf._prior_index(rows, 2, 340, 395) == 0
    assert sf._prior_index(rows, 2, 70, 110) == 1
    assert sf._prior_index(rows, 1, 340, 395) is None


def test_build_rejects_other_markets_with_a_clear_status():
    payload = sf.build_financials("600519.SH")
    assert payload["status"] == "unsupported" and payload["metrics"] == []


# ---------- SEC ----------

def _fact(start, end, val, fp, accn, filed, form="10-Q", fy=2099):
    row = {"end": end, "val": val, "fp": fp, "accn": accn, "filed": filed, "form": form, "fy": fy}
    if start:
        row["start"] = start
    return row


def _facts():
    q1, q2, fy = "A-1", "A-2", "A-K"
    revenue = [
        _fact("2099-01-01", "2099-03-31", 100, "Q1", q1, "2099-04-20"),
        _fact("2099-04-01", "2099-06-30", 110, "Q2", q2, "2099-07-20"),
        _fact("2099-01-01", "2099-06-30", 210, "Q2", q2, "2099-07-20"),
    ]
    ocf = [
        _fact("2099-01-01", "2099-03-31", 40, "Q1", q1, "2099-04-20"),
        _fact("2099-01-01", "2099-06-30", 90, "Q2", q2, "2099-07-20"),
        _fact("2099-01-01", "2099-12-31", 300, "FY", fy, "2100-02-01", form="10-K"),
        _fact("2099-01-01", "2099-09-30", 200, "Q3", "A-3", "2099-10-20"),
    ]
    capex = [
        _fact("2099-01-01", "2099-03-31", 5, "Q1", q1, "2099-04-20"),
        _fact("2099-01-01", "2099-06-30", 12, "Q2", q2, "2099-07-20"),
    ]
    eps = [_fact("2099-01-01", "2099-03-31", 1.1, "Q1", q1, "2099-04-20"),
           _fact("2099-04-01", "2099-06-30", 1.2, "Q2", q2, "2099-07-20"),
           _fact("2099-01-01", "2099-06-30", 2.3, "Q2", q2, "2099-07-20")]
    assets = [_fact(None, "2099-06-30", 1000, "Q2", q2, "2099-07-20")]
    contract = [_fact(None, "2090-06-30", 777, "Q2", "OLD", "2090-07-20", fy=2090)]
    return {"entityName": "Test", "facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": revenue}},
        "NetIncomeLoss": {"units": {"USD": [_fact("2099-04-01", "2099-06-30", 30, "Q2", q2, "2099-07-20")]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": capex}},
        "EarningsPerShareBasic": {"units": {"USD/shares": eps}},
        "Assets": {"units": {"USD": assets}},
        "ContractWithCustomerLiability": {"units": {"USD": contract}},
    }}}


def test_sec_picks_single_quarter_not_year_to_date():
    rows = _by_key(us.parse_companyfacts(_facts())["periods"])
    assert rows["2099Q2"]["raw"]["revenue"] == 110
    assert rows["2099Q2"]["raw"]["eps"] == 1.2


def test_sec_differences_year_to_date_cash_flow():
    rows = _by_key(us.parse_companyfacts(_facts())["periods"])
    assert rows["2099Q2"]["raw"]["ocf"] == 50
    assert rows["2099Q2"]["raw"]["capex"] == 7
    assert "ocf" in rows["2099Q2"]["derived"]


def test_sec_q4_is_full_year_minus_nine_months():
    rows = _by_key(us.parse_companyfacts(_facts())["periods"])
    assert rows["2099Q4"]["raw"]["ocf"] == 100


def test_sec_old_tag_never_leaks_into_recent_period():
    """INTC 實測：合約負債 tag 停在 2021，不能拿最後一筆充當當季。"""
    rows = _by_key(us.parse_companyfacts(_facts())["periods"])
    assert rows["2099Q2"]["raw"]["contract"] is None


def test_sec_restated_value_uses_latest_filing_but_keeps_first_announce_date():
    facts = _facts()
    facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"].append(
        _fact("2099-04-01", "2099-06-30", 115, "Q3", "A-3", "2099-10-20"))
    rows = _by_key(us.parse_companyfacts(facts)["periods"])
    assert rows["2099Q2"]["raw"]["revenue"] == 115
    assert rows["2099Q2"]["announce_date"] == "2099-07-20"


def test_sec_without_quarterly_gaap_returns_none_for_yfinance_fallback():
    assert us.parse_companyfacts({"facts": {"ifrs-full": {"Revenue": {}}}}) is None


def test_sec_does_not_mix_other_currency_units():
    facts = _facts()
    facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["EUR"] = [
        _fact("2099-07-01", "2099-09-30", 999, "Q3", "A-3", "2099-10-20")]
    parsed = us.parse_companyfacts(facts)
    assert parsed["currency"] == "USD"
    assert _by_key(parsed["periods"])["2099Q3"]["raw"]["revenue"] is None


def test_sec_reporting_currency_is_the_dominant_unit_not_any_unit():
    facts = _facts()
    facts["facts"]["us-gaap"]["Assets"]["units"]["ZAR"] = [
        _fact(None, "2099-06-30", 5, "Q2", "A-2", "2099-07-20")]
    assert us.parse_companyfacts(facts)["currency"] == "USD"


def test_sec_amendment_does_not_replace_first_announce_date():
    facts = _facts()
    facts["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"].append(
        _fact("2099-04-01", "2099-06-30", 31, "Q2", "A-2A", "2099-12-01", form="10-Q/A"))
    rows = _by_key(us.parse_companyfacts(facts)["periods"])
    assert rows["2099Q2"]["announce_date"] == "2099-07-20"
    assert rows["2099Q2"]["raw"]["net_income"] == 31


def _period(end, **raw):
    return {"key": end[:4], "period_end": end, "raw": raw}


def test_cross_check_reports_mismatch_and_matches_within_tolerance():
    primary = [_period("2099-06-27", revenue=100.0, op_income=10.0)]
    secondary = [_period("2099-06-30", revenue=100.5, op_income=19.0)]
    result = us.cross_check(primary, secondary)
    assert result["status"] == "mismatch" and result["compared"] == 2
    assert [item["field"] for item in result["mismatches"]] == ["op_income"]


def test_cross_check_unavailable_without_overlap():
    assert us.cross_check([_period("2099-06-27", revenue=1.0)], [])["status"] == "unavailable"


class _Frame:
    pass


def test_yfinance_capex_sign_currency_and_incomplete_quarter(monkeypatch):
    import pandas as pd

    columns = [pd.Timestamp("2099-09-30"), pd.Timestamp("2099-06-30")]
    income = pd.DataFrame({columns[0]: [float("nan"), float("nan"), 0.6],
                           columns[1]: [100.0, 30.0, 1.0]}, index=["Total Revenue", "Net Income", "Basic EPS"])
    cash = pd.DataFrame({columns[1]: [-8.0, 20.0]}, index=["Capital Expenditure", "Operating Cash Flow"])

    class Ticker:
        def __init__(self, symbol):
            self.quarterly_income_stmt = income
            self.quarterly_cashflow = cash
            self.quarterly_balance_sheet = pd.DataFrame()

        def get_info(self):
            return {"quoteType": "EQUITY", "financialCurrency": "TWD", "currency": "USD"}

    monkeypatch.setattr("yfinance.Ticker", Ticker)
    result = us.fetch_yfinance_periods("TSM")
    assert result["currency"] == "TWD" and result["trading_currency"] == "USD"
    assert [row["key"] for row in result["periods"]] == ["2099Q2"]
    assert result["periods"][0]["raw"]["capex"] == 8.0


@pytest.mark.parametrize("quote_type,status", [("ETF", "not_applicable"), ("EQUITY", "no_data")])
def test_us_etf_is_not_applicable_rather_than_empty(monkeypatch, quote_type, status):
    monkeypatch.setattr("src.services.us_financials.fetch_us_financials", lambda code: {
        "source": "yfinance", "currency": "USD", "trading_currency": "USD", "periods": [], "cross_check": None,
        "financial": False, "quote_type": quote_type, "limitations": [], "error": False})
    assert sf._us_payload("SPY")["status"] == status


def test_us_adr_labels_reporting_currency_and_adr_eps(monkeypatch):
    row = {"key": "2099Q2", "label": "2099 Q2", "fiscal_year": 2099, "fiscal_quarter": 2, "period_end": "2099-06-30",
           "announce_date": None, "announce_date_kind": "unknown", "filing_form": "",
           "raw": {"revenue": 1e12, "eps": 136.25}, "derived": set()}
    monkeypatch.setattr("src.services.us_financials.fetch_us_financials", lambda code: {
        "source": "yfinance", "currency": "TWD", "trading_currency": "USD", "periods": [row], "cross_check": None,
        "financial": False, "quote_type": "EQUITY", "limitations": [], "error": False})
    payload = sf._us_payload("TSM")
    assert payload["currency"] == "TWD" and payload["trading_currency"] == "USD"
    assert {m["key"]: m["unit"] for m in payload["metrics"]}["revenue"] == "TWD"
    assert {m["key"]: m["unit"] for m in payload["metrics"]}["eps"] == "TWD/ADR"
    assert any("不能直接相除" in text for text in payload["limitations"])


def test_source_failure_returns_unavailable_status(monkeypatch):
    def boom(code, today):
        raise RuntimeError("db down")

    monkeypatch.setattr(sf, "_tw_payload", boom)
    assert sf.build_financials("2330.TW")["status"] == "unavailable"
