"""月營收法定公告期限：共用規則本身與寫入端維持次月 10 日佔位的迴歸測試。"""

from pathlib import Path

import pandas as pd
import pytest

from market_data import etl, sources
from market_data.revenue_deadline import (
    effective_announce_dates,
    is_insurance_class,
    publication_deadline,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "mops_company_revenue.html"


@pytest.mark.parametrize("sid, month, expected", [
    ("2881", "2026-03-01", "2026-04-15"),     # 保險類：2026 起 15 日
    ("2881.TW", "2026-01-01", "2026-02-15"),  # 第一個適用月（2 月申報 1 月營收）
    ("5880", "2026-03-01", "2026-04-15"),     # 非 28xx 但具保險子公司（合庫金）
    ("2330", "2026-03-01", "2026-04-10"),     # 反向：一般公司仍 10 日
    ("2881", "2025-12-01", "2026-01-10"),     # 反向：規則起點之前仍 10 日
    ("2881", "2026-12-01", "2027-01-15"),     # 跨年
    ("2330", "2020-01-01", "2020-02-15"),     # 疫情全面展延
    ("2881", "2020-01-01", "2020-02-15"),
    ("2330", "2020-02-01", "2020-03-10"),     # 反向：展延只限 2020-01
])
def test_publication_deadline(sid, month, expected):
    assert publication_deadline(sid, month) == pd.Timestamp(expected)


def test_insurance_class_is_conservative_prefix_plus_extras():
    assert is_insurance_class("2801") and is_insurance_class("2207.TW")
    assert not is_insurance_class("2330") and not is_insurance_class("1281")


def test_effective_dates_keep_later_actual_and_nat():
    ann = pd.Series(pd.to_datetime(["2026-04-10", "2026-04-20", None]))
    out = effective_announce_dates(pd.Series(["2881", "2881", "2881"]), ann,
                                   pd.Series(pd.to_datetime(["2026-03-01"] * 3)))
    assert out.iloc[0] == pd.Timestamp("2026-04-15")
    assert out.iloc[1] == pd.Timestamp("2026-04-20")   # 晚於期限的不往前拉
    assert pd.isna(out.iloc[2])
    assert out.dtype == ann.dtype


def test_etl_monthly_revenue_keeps_tenth_placeholder():
    # 寫入端維持次月 10 日佔位不變，法定期限由回測讀取端（revenue_deadline）套用
    df = pd.DataFrame({"stock_id": ["2881", "2330", "2330"],
                       "date": ["2026-04-10", "2026-04-10", "2020-02-10"],
                       "當月營收": [1, 2, 3], "去年同月增減(%)": [1.0, 2.0, 3.0],
                       "上月比較增減(%)": [0.0, 0.0, 0.0]})
    out = etl.transform_monthly_revenue(df)
    assert [str(d)[:10] for d in out["announce_date"]] == ["2026-04-10", "2026-04-10", "2020-02-10"]
    assert [str(d)[:10] for d in out["revenue_month"]] == ["2026-03-01", "2026-03-01", "2020-01-01"]


@pytest.mark.parametrize("sid, roc, year, month, expected", [
    ("2881", "115年03月", 2026, 3, "2026-04-10"),
    ("2330", "115年03月", 2026, 3, "2026-04-10"),
    ("2330", "109年01月", 2020, 1, "2020-02-10"),
    ("2881", "115年12月", 2026, 12, "2027-01-10"),
])
def test_company_revenue_page_announce_keeps_tenth_placeholder(sid, roc, year, month, expected):
    html = FIX.read_text(encoding="utf-8", errors="replace").replace("109年06月", roc)
    rec, reason = sources.parse_company_monthly_revenue(html, sid, year, month)
    assert reason == "ok"
    assert str(rec["announce_date"])[:10] == expected
