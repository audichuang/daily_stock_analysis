import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import tw_ptt_picks as tp  # noqa: E402

INDEX = [("6811.TWO", "宏碁資訊", []), ("2316.TW", "楠梓電", []), ("3045.TW", "台灣大", []),
         ("0052.TW", "富邦科技", [])]

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
    assert tp.resolve_target("宏碁資訊-6811", INDEX) == ("6811.TWO", "code")
    assert tp.resolve_target("2316.TW 楠梓電", INDEX) == ("2316.TW", "code")
    assert tp.resolve_target("楠梓電", INDEX) == ("2316.TW", "exact")
    assert tp.resolve_target("台灣大盤", INDEX) == (None, "market")
    assert tp.resolve_target("0052 台股科技", INDEX) == ("0052.TW", "code")  # a typed code beats the market words
    assert tp.resolve_target("SOXS", INDEX) == (None, "unresolved")


def test_data_cutoff_uses_previous_close_before_1330():
    assert tp.data_cutoff(tp.post_time("M.1792560300.A.000")) == date(2026, 10, 20)  # 13:25 Taipei
    assert tp.data_cutoff(tp.post_time("M.1792560600.A.000")) == date(2026, 10, 21)  # 13:30 Taipei


def test_parse_search_keeps_only_original_target_posts():
    html_ = ('<a href="/bbs/Stock/M.1.A.AAA.html">[標的] 2316 楠梓電</a>'
             '<a href="/bbs/Stock/M.2.A.BBB.html">Re: [標的] 2316 楠梓電</a>'
             '<a href="/bbs/Stock/M.3.A.CCC.html">[新聞] 台積電法說</a>')
    assert tp.parse_search(html_) == [("M.1.A.AAA", "[標的] 2316 楠梓電")]
