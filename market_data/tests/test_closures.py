import datetime

from market_data import closures, health

D = datetime.date


def _page(updated, taipei_text):
    return f"""
    更新時間：{updated} 09:29:03
    <TR><TD headers="city_Name Keelung City"><FONT>基隆市</FONT></TD>
        <TD><FONT>今天停止上班、停止上課。</FONT></TD></TR>
    <TR><TD vAlign=center headers="city_Name Taipei City"><FONT>臺北市</FONT></TD>
        <TD vAlign=center align=left><FONT color=#FF0000 >{taipei_text}  </FONT></TD></TR>
    """


def test_parse_dgpa_full_day_relative_to_page_update_date():
    assert closures.parse_dgpa(_page("2099/03/02", "今天停止上班、停止上課。")) == {D(2099, 3, 2)}
    # Announced the evening before: "明天" is relative to the page's own update time.
    assert closures.parse_dgpa(_page("2099/03/01", "明天停止上班、停止上課。")) == {D(2099, 3, 2)}


def test_parse_dgpa_ignores_half_day_and_other_cities():
    assert closures.parse_dgpa(_page("2099/03/02", "今天上午照常上班、下午停止上班。")) == set()
    assert closures.parse_dgpa(_page("2099/03/02", "今天下午停止上班、停止上課。")) == set()
    assert closures.parse_dgpa(_page("2099/03/02", "照常上班、照常上課。")) == set()


def test_parse_dgpa_morning_suspension_closes_market():
    # TWSE rule: a morning suspension closes the whole session; only afternoon ones do not.
    assert closures.parse_dgpa(_page("2099/03/01", "明天上午停止上班、停止上課。")) == {D(2099, 3, 2)}
    assert closures.parse_dgpa(
        _page("2099/03/02", "今天上午停止上班、停止上課，下午照常上班、照常上課。")) == {D(2099, 3, 2)}
    assert closures.parse_dgpa(_page("2099/03/02", "今天照常上班、照常上課。明天停止上班、停止上課。")) == {D(2099, 3, 3)}


def test_parse_dgpa_school_level_suspension_is_not_city_wide():
    # Real 2025-10-21 text: Taipei worked normally, only a few schools closed; TWSE traded.
    text = ("今天照常上班、照常上課。  </FONT><br><FONT color=#FF0000 >"
            "臺北市士林區平等國民小學:今天停止上班、停止上課。  </FONT><br><FONT color=#FF0000 >"
            "臺北市溪山實驗國民小學:今天停止上班、停止上課。")
    assert closures.parse_dgpa(_page("2099/03/02", text)) == set()


def test_parse_dgpa_reads_pre_2025_11_layout():
    html = ("更新時間：2099/03/02 05:00:00 <TBODY><TR><TD headers='city_Name' vAlign=center "
            "align=middle width='13%'><FONT >臺北市</FONT></TD><TD headers='StopWorkSchool_Info' "
            "vAlign=center align=left width='70%'><FONT color=#FF0000 >今天停止上班、停止上課。  "
            "</FONT></TD></TR><TR><TD headers='city_Name'><FONT >新北市</FONT></TD><TD>"
            "<FONT>今天照常上班。</FONT></TD></TR>")
    assert closures.parse_dgpa(html) == {D(2099, 3, 2)}


def test_fetch_warns_when_layout_unrecognised(monkeypatch, capsys):
    import requests

    class _Resp:
        text = "<html>改版</html>"
        encoding = None

        def raise_for_status(self):
            pass

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    assert closures.fetch_dgpa_closures() is None
    assert "版面認不出來" in capsys.readouterr().err


def test_parse_dgpa_unknown_layout_is_none():
    assert closures.parse_dgpa("<html>改版</html>") is None


def test_closed_reason_records_dgpa_closure(tmp_path):
    path = tmp_path / "closed.txt"
    today = D(2026, 10, 23)
    reason = closures.tw_closed_reason(today, fetch=lambda: {today}, path=path, today=today)
    assert reason and "停止上班" in reason
    assert closures.adhoc_closed_dates(path) == {today}
    # Recorded: later checks (other days, page no longer showing it) still know.
    assert closures.tw_closed_reason(today, fetch=lambda: None, path=path, today=D(2026, 10, 27))


def test_closed_reason_open_when_page_says_nothing_or_unreachable(tmp_path):
    path = tmp_path / "closed.txt"
    today = D(2026, 10, 22)
    assert closures.tw_closed_reason(today, fetch=lambda: set(), path=path, today=today) is None
    assert closures.tw_closed_reason(today, fetch=lambda: None, path=path, today=today) is None
    assert not path.exists()


def test_page_only_consulted_for_today(tmp_path):
    calls = []
    closures.tw_closed_reason(D(2026, 10, 22), fetch=lambda: calls.append(1) or {D(2026, 10, 22)},
                              path=tmp_path / "c.txt", today=D(2026, 10, 23))
    assert calls == []


def test_health_session_checker_skips_listed_closure(tmp_path, monkeypatch):
    path = tmp_path / "closed.txt"
    path.write_text("2026-10-23  # typhoon\n", encoding="utf-8")
    monkeypatch.setenv("TW_ADHOC_CLOSED_FILE", str(path))
    is_session = health._xtai_session_checker()
    assert is_session(D(2026, 10, 22)) is True
    assert is_session(D(2026, 10, 23)) is False
    # 10-26 is a calendar holiday, so the first session before 10-27 is 10-22.
    assert health.session_before(D(2026, 10, 27), is_session=is_session) == D(2026, 10, 22)
    after_close = datetime.datetime(2026, 10, 23, 18, 1)
    assert health.expected_session(after_close, is_session=is_session) == D(2026, 10, 22)


def test_is_market_open_honours_closure_list(tmp_path, monkeypatch):
    from src.core.trading_calendar import is_market_open

    path = tmp_path / "closed.txt"
    monkeypatch.setenv("TW_ADHOC_CLOSED_FILE", str(path))
    assert is_market_open("tw", D(2026, 10, 23)) is True
    path.write_text("2026-10-23\n", encoding="utf-8")
    assert is_market_open("tw", D(2026, 10, 23)) is False
    assert is_market_open("us", D(2026, 10, 23)) is True


def test_trading_calendar_helpers_skip_listed_closure(tmp_path, monkeypatch):
    from datetime import datetime

    from src.core.trading_calendar import count_missing_sessions, get_effective_trading_date, get_trading_dates

    path = tmp_path / "closed.txt"
    path.write_text("2026-10-23\n", encoding="utf-8")
    monkeypatch.setenv("TW_ADHOC_CLOSED_FILE", str(path))
    sessions = [d.date() for d in get_trading_dates("tw", D(2026, 10, 21), D(2026, 10, 27))]
    assert sessions == [D(2026, 10, 21), D(2026, 10, 22), D(2026, 10, 27)]
    assert get_effective_trading_date("tw", datetime(2026, 10, 26, 11, 0)) == D(2026, 10, 22)
    assert count_missing_sessions("tw", D(2026, 10, 22), datetime(2026, 10, 26, 15, 0)) == 0
    # Without the list the bundled calendar still treats the typhoon day as a session.
    monkeypatch.setenv("TW_ADHOC_CLOSED_FILE", str(tmp_path / "absent.txt"))
    assert get_effective_trading_date("tw", datetime(2026, 10, 26, 11, 0)) == D(2026, 10, 23)
