"""月營收法定公告期限：共用規則本身與寫入端維持次月 10 日佔位的迴歸測試。"""

import datetime as dt
import logging
from pathlib import Path

import pandas as pd
import pytest

from market_data import etl, health, sources
from market_data.revenue_deadline import (
    apply_revenue_deadline,
    effective_announce_dates,
    is_insurance_class,
    publication_deadline,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "mops_company_revenue.html"


def _always_open(day):
    return True   # 只驗法定日規則本身、不含休市順延


def _weekdays_except(*closed):
    closed = {dt.date.fromisoformat(d) for d in closed}
    return lambda day: day.weekday() < 5 and day not in closed


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
    ("2905", "2026-03-01", "2026-04-15"),     # 三商投控（持有三商美邦人壽）
    ("2905.TW", "2026-01-01", "2026-02-15"),
    ("2905", "2025-12-01", "2026-01-10"),     # 反向：規則起點之前仍 10 日
    ("2903", "2026-03-01", "2026-04-10"),     # 反向：同為 29xx 的遠百不適用
])
def test_publication_deadline(sid, month, expected):
    assert publication_deadline(sid, month, is_session=_always_open) == pd.Timestamp(expected)


def test_insurance_class_is_conservative_prefix_plus_extras():
    assert is_insurance_class("2801") and is_insurance_class("2207.TW")
    assert is_insurance_class("2905") and is_insurance_class("2905.TW")
    assert not is_insurance_class("2330") and not is_insurance_class("1281")
    assert not is_insurance_class("2903") and not is_insurance_class("12905")


def test_vectorized_insurance_class_includes_2905():
    ann = pd.Series(pd.to_datetime(["2026-04-10"] * 3))
    out = effective_announce_dates(pd.Series(["2905", "2207", "2330"]), ann,
                                   pd.Series(pd.to_datetime(["2026-03-01"] * 3)),
                                   is_session=_always_open)
    assert out.tolist() == [pd.Timestamp("2026-04-15"), pd.Timestamp("2026-04-15"),
                            pd.Timestamp("2026-04-10")]


@pytest.mark.parametrize("sid, month, closed, expected", [
    ("2330", "2026-04-01", (), "2026-05-11"),               # 週日 05-10 → 週一
    ("2330", "2026-04-01", ("2026-05-11",), "2026-05-12"),  # 週一也休市（颱風假）→ 再順延
    ("2881", "2026-01-01", (), "2026-02-16"),               # 保險類 15 日落週日
    ("2330", "2020-01-01", (), "2020-02-17"),               # 展延日 2020-02-15 是週六
    ("2330", "2026-03-01", (), "2026-04-10"),               # 反向：週五交易日不順延
    ("2881", "2026-03-01", (), "2026-04-15"),               # 反向：週三交易日不順延
    ("2330", "2026-03-01", ("2026-04-13",), "2026-04-10"),  # 反向：隔週休市與期限無關
])
def test_deadline_rolls_to_next_session(sid, month, closed, expected):
    cal = _weekdays_except(*closed)
    assert publication_deadline(sid, month, is_session=cal) == pd.Timestamp(expected)
    # 向量化版與純量版同一結果（回測讀取端走向量化版）
    ann = pd.Series(pd.to_datetime([None]))
    vec = effective_announce_dates(pd.Series([sid]), pd.Series([pd.Timestamp(month) + pd.DateOffset(months=1)]),
                                   pd.Series([pd.Timestamp(month)]), is_session=cal)
    assert vec.iloc[0] == pd.Timestamp(expected)
    assert pd.isna(effective_announce_dates(pd.Series([sid]), ann, is_session=cal).iloc[0])


def test_deadline_without_calendar_rolls_weekends_only(monkeypatch, caplog):
    # 日曆不可用（未安裝／超出範圍）：週六日一定不是交易日，至少順延到週一；不能維持原日
    monkeypatch.setattr(health, "_xtai_session_checker", lambda autodetect=True: None)
    with caplog.at_level(logging.WARNING, logger="market_data.revenue_deadline"):
        assert publication_deadline("2330", "2026-04-01") == pd.Timestamp("2026-05-11")
    assert "只順延週六日" in caplog.text
    assert publication_deadline("2330", "2026-03-01") == pd.Timestamp("2026-04-10")   # 反向：平日不動

    def out_of_range(day):
        raise ValueError("out of calendar range")

    df = pd.DataFrame({"stock_id": ["2330", "2881"],
                       "revenue_month": pd.to_datetime(["2026-04-01", "2026-03-01"]),
                       "date": pd.to_datetime(["2026-05-10", "2026-04-10"])})
    out = apply_revenue_deadline(df, is_session=out_of_range)
    assert out["date"].tolist() == [pd.Timestamp("2026-05-11"), pd.Timestamp("2026-04-15")]


def test_default_calendar_is_offline_and_rolls_real_holidays(monkeypatch, tmp_path):
    pytest.importorskip("exchange_calendars")
    monkeypatch.setenv("TW_ADHOC_CLOSED_FILE", str(tmp_path / "none.txt"))   # 不受本機休市清單影響
    # 預設日曆只讀本機休市清單、不連網偵測（回測一次算上百個日期）
    monkeypatch.setattr(health, "autodetect_today",
                        lambda: (_ for _ in ()).throw(AssertionError("不該連網偵測")))
    assert publication_deadline("2330.TW", "2026-04-01") == pd.Timestamp("2026-05-11")
    # 2026-02-15（週日）落在春節休市（02-16~02-20），順延到開市第一天 02-23
    assert publication_deadline("2881", "2026-01-01") == pd.Timestamp("2026-02-23")
    assert publication_deadline("2905", "2026-01-01") == pd.Timestamp("2026-02-23")
    assert publication_deadline("2330", "2026-03-01") == pd.Timestamp("2026-04-10")


def test_effective_dates_keep_later_actual_and_nat():
    ann = pd.Series(pd.to_datetime(["2026-04-10", "2026-04-20", None]))
    out = effective_announce_dates(pd.Series(["2881", "2881", "2881"]), ann,
                                   pd.Series(pd.to_datetime(["2026-03-01"] * 3)),
                                   is_session=_always_open)
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
