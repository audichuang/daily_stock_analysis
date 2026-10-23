import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import tw_ptt_picks as tp  # noqa: E402

INDEX = [("6811.TWO", "宏碁資訊", []), ("2316.TW", "楠梓電", []), ("3045.TW", "台灣大", []),
         ("0052.TW", "富邦科技", []), ("2330.TW", "台積電", []), ("1810.TW", "和成", []), ("2025.TW", "千興", [])]

META = ('<div id="main-content" class="bbs-screen bbs-content"><div class="article-metaline">'
        '<span class="article-meta-tag">作者</span><span class="article-meta-value">someone (暱稱)</span></div>'
        '<div class="article-metaline"><span class="article-meta-tag">標題</span>'
        '<span class="article-meta-value">[標的] 宏碁資訊6811-多</span></div>\n' + "-" * 73 + "\n\n")
PUSHES = ('<div class="push"><span class="hl push-tag">推 </span><span>a</span></div>'
          '<div class="push"><span class="f1 hl push-tag">噓 </span><span>b</span></div>'
          '<div class="push"><span class="f1 hl push-tag">→ </span><span>c</span></div>')


def page(body: str) -> str:
    return META + body + "\n--\n※ 發信站: 批踢踢實業坊(ptt.cc)\n" + PUSHES


def test_parse_article_reads_numbered_template_fields_and_drops_footer():
    p = tp.parse_article(page(
        "1.標的：宏碁資訊-6811\n2.分類：多\n3.分析/正文：營收創高\n籌碼面：外資布局\n"
        "4.進退場機制：\n進場：270\n停損：260\n(喊多喊空者，必須有停損機制。 長期投資、討論、心得類免填)\n"
        "對帳單：\nhttps://i.example/x.jpg\n-----\nSent from MeowPtt\n"), "[標的] 宏碁資訊6811-多")
    assert p["target"] == "宏碁資訊-6811"
    assert p["category"] == "多" and p["stance"] == "bullish"
    assert p["reason"] == "營收創高 籌碼面：外資布局"  # inline 籌碼面： is not a template label
    assert p["condition"] == "進場：270 停損：260"
    assert p["has_statement"] is True
    assert (p["push_up"], p["push_down"], p["push_neutral"]) == (1, 1, 1)


def test_parse_article_without_template_keeps_text_and_title():
    p = tp.parse_article(page("從7XXX開始關注\n最近漲幅可觀\n"), "[標的] 2059川湖 操作空間?")
    assert p["target"] == "2059川湖 操作空間?"
    assert p["reason"] == "從7XXX開始關注 最近漲幅可觀"
    assert p["stance"] == "neutral" and p["condition"] is None and p["has_statement"] is False


def test_stance_of_needs_one_side_only():
    assert tp.stance_of("長期持有多", "[標的] 0052") == "bullish"
    assert tp.stance_of("多/討論", "[標的] 台指期") == "bullish"
    assert tp.stance_of("空", "[標的] x") == "bearish"
    assert tp.stance_of("多空都有可能", "[標的] x") == "neutral"
    assert tp.stance_of("討論", "[標的] 大盤 打底進場多？ 請益") == "neutral"
    assert tp.stance_of(None, "[標的] 台股左側交易 下周一跌破季線多") == "bullish"
    assert tp.stance_of(None, "[標的] 2059川湖 操作空間?") == "neutral"  # 空間 is not 空


def test_resolve_target_uses_typed_code_and_keeps_market_out_of_fuzzy():
    assert tp.resolve_target("宏碁資訊-6811", INDEX) == ("6811.TWO", "exact")
    assert tp.resolve_target("2316.TW 楠梓電", INDEX) == ("2316.TW", "code")
    assert tp.resolve_target("楠梓電", INDEX) == ("2316.TW", "exact")
    assert tp.resolve_target("台灣大盤", INDEX) == (None, "market")
    assert tp.resolve_target("0052 富邦科技 台股", INDEX) == ("0052.TW", "code")  # a typed code beats the market words
    assert tp.resolve_target("SOXS", INDEX) == (None, "unresolved")


def test_data_cutoff_waits_for_the_day_to_be_public():
    # the close is out at 13:30 but per-stock institutional flows only later; 17:00 covers both
    assert tp.data_cutoff(tp.post_time("M.1792560660.A.000")) == date(2026, 10, 20)  # 13:31 Taipei
    assert tp.data_cutoff(tp.post_time("M.1792573140.A.000")) == date(2026, 10, 20)  # 16:59
    assert tp.data_cutoff(tp.post_time("M.1792573200.A.000")) == date(2026, 10, 21)  # 17:00


def test_template_examples_and_foreign_or_year_numbers_are_not_trusted_codes():
    assert tp.resolve_target(tp.parse_article(page("標的：(例 2330.TW 台積電) MU.US美光\n分類：多\n"),
                                              "[標的] MU 美光 多")["target"], INDEX)[0] is None
    # a foreign ticker sharing no name with the local company is not attached to it
    assert tp.resolve_target("1810小米集團-W (例 2330 台積電)", INDEX) == (None, "unresolved")
    assert tp.resolve_target("台積電 2025目標", INDEX)[1] != "code"
    assert tp.resolve_target("2330 台積電", INDEX) == ("2330.TW", "exact")


def test_unfilled_category_template_falls_back_to_the_title():
    p = tp.parse_article(page("標的：2316 楠梓電\n分類：多/空/討論/心得 (請選擇並刪除無關分類)\n分析/正文：x\n"),
                         "[標的] 2316 楠梓電 多")
    assert p["category"] is None and p["stance"] == "bullish"


def test_non_article_page_is_an_error_not_a_row():
    import pytest

    with pytest.raises(ValueError):
        tp.parse_article("<html><body>Service unavailable</body></html>", "[標的] 2330 多")


def test_edit_time_is_kept_so_backtests_can_tell_rewritten_posts():
    edits = ("※ 編輯: a (1.2.3.4 臺灣), 10/19/2026 22:00:37\n"
             "※ 編輯: a (1.2.3.4 臺灣), 10/21/2026 09:01:57\n")
    assert tp.parse_article(page("標的：2316\n") + edits, "[標的] 2316")["edited_at"] == "2026-10-21T09:01:57+08:00"
    assert tp.parse_article(page("標的：2316\n"), "[標的] 2316")["edited_at"] is None


def test_parse_search_keeps_only_original_target_posts():
    html_ = ('<a href="/bbs/Stock/M.1.A.AAA.html">[標的] 2316 楠梓電</a>'
             '<a href="/bbs/Stock/M.2.A.BBB.html">Re: [標的] 2316 楠梓電</a>'
             '<a href="/bbs/Stock/M.3.A.CCC.html">[新聞] 台積電法說</a>')
    assert tp.parse_search(html_) == [("M.1.A.AAA", "[標的] 2316 楠梓電")]


def test_template_cleanup_keeps_prose_that_starts_with_例():
    p = tp.parse_article(page("標的：2316 楠梓電\n進退場機制：1000 進場（例外：跌破 900 立即停損）\n"), "[標的] 2316")
    assert p["condition"] == "1000 進場（例外：跌破 900 立即停損）"


def _search(*entries):
    return "".join(f'<a href="/bbs/Stock/{aid}.html">{title}</a>' for aid, title in entries)


# 2026-10-21 / 10-21 / 09-22 Taipei
NEW1, NEW2, OLD = "M.1792560350.A.0E7", "M.1792560400.A.111", "M.1790000000.A.222"


def test_new_articles_reads_past_a_page_of_replies(monkeypatch):
    pages = {1: _search((NEW1, "Re: [標的] 2316 楠梓電")), 2: _search((NEW2, "[標的] 2316 楠梓電")),
             3: _search((OLD, "[標的] 舊文"))}
    monkeypatch.setattr(tp, "_get", lambda url: pages[int(url.split("page=")[1].split("&")[0])])
    monkeypatch.setattr(tp.time, "sleep", lambda s: None)
    got = tp.new_articles(date(2026, 10, 20), set())
    assert [a["article_id"] for a in got] == [NEW2]


def test_new_articles_stops_at_an_old_reply_and_past_the_last_page(monkeypatch):
    import requests

    def get(url):
        page = int(url.split("page=")[1].split("&")[0])
        if page == 1:
            return _search((NEW2, "[標的] 新"), (OLD, "Re: [標的] 舊"))
        raise AssertionError("an older reply already proves the rest is older")

    monkeypatch.setattr(tp, "_get", get)
    assert [a["article_id"] for a in tp.new_articles(date(2026, 10, 20), set())] == [NEW2]

    def get404(url):
        if "page=1&" in url:
            return _search((NEW2, "[標的] 新"))
        raise requests.HTTPError(response=type("R", (), {"status_code": 404})())

    monkeypatch.setattr(tp, "_get", get404)
    monkeypatch.setattr(tp.time, "sleep", lambda s: None)
    assert [a["article_id"] for a in tp.new_articles(date(2026, 10, 20), set())] == [NEW2]


def test_new_articles_fails_loudly_when_the_search_page_has_no_entries(monkeypatch):
    import pytest

    monkeypatch.setattr(tp, "_get", lambda url: "<html>改版或擋爬</html>")
    with pytest.raises(RuntimeError):
        tp.new_articles(date(2026, 10, 20), set())


def test_snapshot_failure_is_retried_instead_of_journaling_null_data(monkeypatch):
    import pytest

    art = {"article_id": NEW2, "title": "[標的] 2316 楠梓電 多", "posted": tp.post_time(NEW2),
           "cutoff": date(2026, 10, 20), "url": "u"}
    html_ = page("標的：2316 楠梓電\n分類：多\n")

    def boom(code, as_of, engine):
        raise ConnectionError("db down")

    monkeypatch.setattr(tp.mp, "snapshot", boom)
    with pytest.raises(ConnectionError):
        tp.build_row(art, html_, INDEX, engine=object(), now="t")
    monkeypatch.setattr(tp.mp, "snapshot", lambda code, as_of, engine: None)  # no history is not a failure
    row = tp.build_row(art, html_, INDEX, engine=object(), now="t")
    assert row["stock_code"] == "2316.TW" and row["data"] is None and row["author"] == "someone"


def test_a_404_on_the_first_search_page_is_an_error_not_an_empty_run(monkeypatch):
    import pytest
    import requests

    def get404(url):
        raise requests.HTTPError(response=type("R", (), {"status_code": 404})())

    monkeypatch.setattr(tp, "_get", get404)
    with pytest.raises(requests.HTTPError):
        tp.new_articles(date(2026, 10, 20), set())
