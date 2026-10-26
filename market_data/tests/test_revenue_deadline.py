"""月營收法定公告期限：共用規則本身與寫入端維持次月 10 日佔位的迴歸測試。"""

from pathlib import Path

import pandas as pd
import pytest

from market_data import etl, sources
from market_data.revenue_deadline import (
    effective_announce_dates,
    is_insurance_class,
    publication_deadline,
    publication_deadline_date,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "mops_company_revenue.html"


@pytest.mark.parametrize("api", ["scalar", "date", "frame"])
@pytest.mark.parametrize("sid, month, expected", [
    ("2905.TW", "2026-03-01", "2026-04-15"),
    ("2905.TW", "2025-11-01", "2025-12-10"),
    ("2330.TW", "2026-03-01", "2026-04-10"),
    ("2330.TW", "2026-04-01", "2026-05-11"),
    ("2905.TW", "2026-07-01", "2026-08-17"),
    ("2905.TW", "2026-01-01", "2026-02-23"),
    ("2330.TW", "2020-01-01", "2020-02-17"),
])
def test_deadline_shared_by_scalar_and_frame(api, sid, month, expected):
    rm = pd.Series(pd.to_datetime([month]))
    ann = rm + pd.DateOffset(months=1) + pd.Timedelta(days=9)
    if api == "scalar":
        out = publication_deadline(sid, month)
    elif api == "date":
        out = publication_deadline_date(sid, rm.iloc[0].year, rm.iloc[0].month)
    else:
        out = effective_announce_dates(pd.Series([sid]), ann, rm).iloc[0]
    assert pd.Timestamp(out) == pd.Timestamp(expected)


def test_deadline_reads_adhoc_closures_without_network(tmp_path, monkeypatch):
    from market_data import health

    path = tmp_path / "closures.txt"
    path.write_text("2026-04-10\n", encoding="utf-8")
    monkeypatch.setenv("TW_ADHOC_CLOSED_FILE", str(path))
    monkeypatch.setattr(health, "autodetect_today", lambda: pytest.fail("不得連網偵測"))
    assert publication_deadline("2330.TW", "2026-03-01") == pd.Timestamp("2026-04-13")
    path.write_text("", encoding="utf-8")
    assert publication_deadline("2330.TW", "2026-03-01") == pd.Timestamp("2026-04-10")


def test_deadline_requires_available_calendar(monkeypatch):
    from market_data import revenue_deadline

    monkeypatch.setattr(revenue_deadline, "_xtai_session_checker", lambda **kw: None)
    with pytest.raises(ValueError, match="無法確認"):
        publication_deadline("2330.TW", "2026-04-01")


@pytest.mark.parametrize("sid, month, expected", [
    ("2881", "2026-03-01", "2026-04-15"),     # 保險類：2026 起 15 日
    ("2881.TW", "2026-01-01", "2026-02-23"),  # 第一個適用月，春節休市順延
    ("5880", "2026-03-01", "2026-04-15"),     # 非 28xx 但具保險子公司（合庫金）
    ("2330", "2026-03-01", "2026-04-10"),     # 反向：一般公司仍 10 日
    ("2881", "2025-12-01", "2026-01-12"),     # 反向：規則起點之前仍 10 日，週末順延
    ("2881", "2026-12-01", "2027-01-15"),     # 跨年
    ("2330", "2020-01-01", "2020-02-17"),     # 疫情全面展延，週末順延
    ("2881", "2020-01-01", "2020-02-17"),
    ("2330", "2020-02-01", "2020-03-10"),     # 反向：展延只限 2020-01
])
def test_publication_deadline(sid, month, expected):
    assert publication_deadline(sid, month) == pd.Timestamp(expected)


def test_insurance_class_is_conservative_prefix_plus_extras():
    assert is_insurance_class("2801") and is_insurance_class("2207.TW") and is_insurance_class("2905.TW")
    assert not is_insurance_class("2330") and not is_insurance_class("1281")


def test_effective_dates_keep_later_actual_and_resolve_known_month():
    ann = pd.Series(pd.to_datetime(["2026-04-10", "2026-04-18", None, None]), index=[3, 5, 7, 9])
    out = effective_announce_dates(pd.Series(["2881"] * 4, index=ann.index), ann,
                                   pd.Series(pd.to_datetime(["2026-03-01"] * 3 + [None]), index=ann.index))
    assert out.iloc[0] == pd.Timestamp("2026-04-15")
    assert out.iloc[1] == pd.Timestamp("2026-04-18")   # 晚於期限的真實公告不拉回或再順延
    assert out.iloc[2] == pd.Timestamp("2026-04-15")
    assert pd.isna(out.iloc[3])
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
