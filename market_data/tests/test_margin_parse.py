"""MI_MARGN 解析:表頭順序核對、註腳列過濾,以及 WARN 訊息區分(純函式,不連線)。"""
import datetime

import pytest

from market_data import sources

D = datetime.date(2026, 10, 15)

# 官方表頭(尾端逗號 = 多一個空欄)與一般資料列
_HEADER = ('"代號","名稱","買進","賣出","現金償還","前日餘額","今日餘額","次一營業日限額",'
           '"買進","賣出","現券償還","前日餘額","今日餘額","次一營業日限額","資券互抵","註記",')


def _csv(header=_HEADER, rows=None, footnotes=True):
    rows = rows if rows is not None else [
        '="2330","台積電","10","20","0","1,000","1,100","5,000","1","2","0","30","31","500","0"," ",',
        '="0050","元大台灣50","5","6","0","200","210","900","0","0","0","0","0","0","0","X",',
        '="00631L","元大台灣50正2","5","6","0","200","210","900","0","0","0","0","0","0","0"," ",',
    ]
    lines = ['"115年10月15日 信用交易統計"', '"項目","買進","賣出","現金(券)償還","前日餘額","今日餘額",',
             '"融資(交易單位)","1","2","3","4","5",', "", header, *rows]
    if footnotes:
        lines += ['', '"備註",', '"備註:"', '"符號說明： O：停止融資, X：停止融券",',
                  '"限額：　融資餘額達該種股票上市股份25%時，暫停融資買進。",']
    return "\r\n".join(lines).encode("cp950")


def test_parse_margin_reads_data_rows_and_drops_footnotes():
    df = sources.parse_margin(_csv(), D)
    assert list(df.index.get_level_values("stock_id")) == ["2330", "0050", "00631L"]  # 帶字母的代號要留,註腳不進
    assert df.loc[("2330", "2026-10-15"), "融資今日餘額"] == 1100


def test_parse_margin_rejects_inserted_column():
    bad = _HEADER.replace('"現金償還",', '"現金償還","新欄",')
    row = '="2330","台積電","10","20","0","9","1,000","1,100","5,000","1","2","0","30","31","500","0"," ",'
    with pytest.raises(ValueError, match="表頭") as ei:
        sources.parse_margin(_csv(header=bad, rows=[row]), D)
    assert "新欄" in str(ei.value)  # 錯誤訊息要列出實際表頭


def test_parse_margin_accepts_header_with_trailing_empty_column():
    # 官方 CSV 表頭尾端多一個逗號;不可要求「恰好 16 欄」
    assert _HEADER.endswith(",")
    assert len(sources.parse_margin(_csv(), D)) == 3


# --- WARN 訊息區分 -----------------------------------------------------------

# 審查時以未來日期實測 MI_MARGN 回的真實 29 bytes(cp950):「查詢日期大於今日，請重新查詢!」
_FUTURE_DATE_REPLY = (b'\xacd\xb8\xdf\xa4\xe9\xb4\xc1\xa4j\xa9\xf3\xa4\xb5\xa4\xe9'
                      b'\xa1A\xbd\xd0\xad\xab\xb7s\xacd\xb8\xdf!')


@pytest.mark.parametrize("crawl", ["crawl_margin", "crawl_institutional"])
def test_short_plain_text_and_html_get_different_warns(monkeypatch, capsys, crawl):
    fn = getattr(sources, crawl)
    monkeypatch.setattr(sources, "_twse_csv", lambda url: _FUTURE_DATE_REPLY)
    assert fn(D) is None
    short = capsys.readouterr().out
    monkeypatch.setattr(sources, "_twse_csv", lambda url: b"<html>blocked</html>")
    assert fn(D) is None
    html = capsys.readouterr().out

    assert short.startswith("**WARN:") and html.startswith("**WARN:")
    assert "TWSE 回覆「查詢日期大於今日，請重新查詢!」" in short
    assert "封鎖頁/改版" not in short
    assert "封鎖頁/改版" in html
    assert "TWSE 回覆" not in html


def test_describe_unparsable_decodes_utf8_before_cp950():
    # UTF-8 短文字若被 cp950 解碼會變亂碼
    msg = sources._describe_unparsable("查詢日期大於今日".encode("utf-8"))
    assert "TWSE 回覆「查詢日期大於今日」" in msg


def test_describe_unparsable_long_plain_text_is_not_a_service_message():
    assert "封鎖頁/改版" in sources._describe_unparsable(b"x" * 600)
    assert "封鎖頁/改版" in sources._describe_unparsable(b"  \n<!DOCTYPE html>")


def test_describe_unparsable_truncates_to_60_chars():
    msg = sources._describe_unparsable(("甲" * 100).encode("utf-8"))
    assert "甲" * 60 in msg and "甲" * 61 not in msg


# --- 回應自帶日期必須等於請求日（週日／停市日官方會回別天的整份表）------------------

@pytest.mark.parametrize("crawl, parse", [("crawl_margin", "parse_margin"),
                                          ("crawl_institutional", "parse_institutional")])
def test_crawl_rejects_a_table_whose_title_date_differs_from_the_request(monkeypatch, capsys, crawl, parse):
    sunday = datetime.date(2026, 10, 18)
    monkeypatch.setattr(sources, "_twse_csv", lambda url: _csv())   # 標題是 115年10月15日
    monkeypatch.setattr(sources, parse, lambda raw, d: "frame")

    assert getattr(sources, crawl)(sunday) is None
    assert "回應日期 2026-10-15 ≠ 請求日 2026-10-18" in capsys.readouterr().out
    assert getattr(sources, crawl)(D) == "frame"                    # 反向：日期相符照收


def test_crawl_rejects_a_table_without_any_title_date(monkeypatch):
    raw = _csv().split(b"\r\n", 1)[1]
    monkeypatch.setattr(sources, "_twse_csv", lambda url: raw)

    assert sources.crawl_margin(D) is None
