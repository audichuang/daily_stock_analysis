"""個股 HTML 報告：缺資料印「無資料」、解讀文字一律跳脫、價位階梯標籤不重疊、
LLM 解讀格式不對就降級、只收台股代號。"""

import json
import re

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.services import tw_stock_report as report  # noqa: E402

EMPTY = {"stock_id": "9999", "name": None, "as_of": "2026-08-28",
         "fundamentals": {"monthly_revenue": [], "ttm_revenue_yoy_pct": None, "quarters": []},
         "contract_liabilities": [],
         "chips": {"institutional": None, "margin": None, "holding": None, "branch": None},
         "valuation": None, "smc": None}


def test_every_section_missing_renders_no_data():
    html = report.render(EMPTY)
    assert html.count(report.NA) >= 8
    assert "未附解讀" in html and "四維度總覽" not in html


def test_narrative_text_is_escaped():
    nar = {"verdicts": {"chips": {"badge": "<b>x</b>", "tone": "pos", "note": "<script>alert(1)</script>"}},
           "followups": ["a<i>"]}
    html = report.render(EMPTY, nar)
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "<b>x</b>" not in html and "a&lt;i&gt;" in html


def test_ladder_labels_do_not_overlap():
    smc = {"price": 100.0, "bsl": [110.0], "ssl": [99.5, 99.0],
           "order_blocks": [{"direction": "bullish", "low": 98.0, "high": 100.5}],
           "fvgs": [{"direction": "bullish", "low": 99.2, "high": 99.8}], "fib": None}
    tops = [float(x) for x in re.findall(r'class="ltag(?: now)?" style="top:([\d.]+)px', report._ladder(smc))]
    assert len(tops) == 6      # 5 levels + 現價
    assert all(b - a >= 17.8 for a, b in zip(tops, tops[1:]))


def test_ladder_distance_uses_near_edge_like_board():
    smc = {"price": 1375.0, "bsl": [], "ssl": [], "fib": None, "fvgs": [],
           "order_blocks": [{"direction": "bullish", "low": 1240.0, "high": 1365.0},
                            {"direction": "bearish", "low": 1360.0, "high": 1400.0},
                            {"direction": "bearish", "low": 1430.0, "high": 1500.0}]}
    dists = re.findall(r'\(([+-][\d.]+)%\)', report._ladder(smc))
    assert dists == ["+4.0", "+0.0", "-0.7"]      # 由高至低；現價在區間內為 0


def _smc(direction):
    return {"price": 100.0, "bsl": [], "ssl": [], "order_blocks": [], "fvgs": [], "swing_n": 3,
            "events": [{"date": "2026-08-27", "kind": "CHOCH", "direction": direction, "level": 95.0}],
            "last_event": {"date": "2026-08-27", "kind": "CHOCH", "direction": direction, "level": 95.0},
            "fib": {"position": 0.3, "zone": "discount", "range_low": 90.0, "range_high": 110.0,
                    "ote_low": 93.0, "ote_high": 96.0, "in_ote": False}}


@pytest.mark.parametrize("direction, verb, ote, wrong_verb, wrong_ote", [
    ("bullish", "突破 95.0", "OTE 多方進場區", "跌破", "OTE 空方進場區"),
    ("bearish", "跌破 95.0", "OTE 空方進場區", "突破", "OTE 多方進場區")])
def test_technical_wording_follows_direction(direction, verb, ote, wrong_verb, wrong_ote):
    html = report.technical({"smc": _smc(direction)}, {})
    assert verb in html and wrong_verb not in html
    assert ote in html and wrong_ote not in html and "最佳進場" not in html


def test_db_derived_fields_are_escaped():
    x = "<i>x</i>"
    p = {**EMPTY, "as_of": x,
         "fundamentals": {"monthly_revenue": [{"month": x, "revenue_k": 1, "yoy_pct": None, "announced": None}],
                          "ttm_revenue_yoy_pct": None,
                          "quarters": [{"quarter": x, "gross_margin": 1, "op_margin": 1, "net_margin": 1, "eps": 1}]},
         "contract_liabilities": [{"quarter": x, "contract_liabilities_k": 1.0}],
         "chips": {"institutional": None, "margin": None, "branch": None,
                   "holding": {"as_of": x, "big_holder_pct": 1.0, "big_holder_pct_wow": 0.0}},
         "valuation": {"as_of": x, "pe_samples_3y": x},
         "smc": {**_smc("bearish"), "events": [{"date": "2026-08-27", "kind": x, "direction": x, "level": 95.0}],
                 "fib": {**_smc("bearish")["fib"], "zone": x}}}
    html = report.render(p)
    low = html.lower()      # direction 會先 .upper()，未跳脫時輸出是 <I>X</I>
    assert "<i>" not in low and "</i>" not in low and "&lt;i&gt;" in low


GOOD = {"verdicts": {k: {"badge": "b", "tone": "neu", "note": "n"} for k in report.VERDICTS},
        "notes": {"revenue": "觀察：x"}, "followups": ["f"]}


def test_parse_narrative_accepts_json_wrapped_in_prose():
    nar = report.parse_narrative("好的，以下是結果：\n```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```")
    assert nar["verdicts"]["chips"]["note"] == "n"


def test_parse_narrative_repairs_trailing_comma():
    broken = json.dumps(GOOD, ensure_ascii=False)[:-1] + ",}"
    assert report.parse_narrative(broken)["followups"] == ["f"]


@pytest.mark.parametrize("text", [None, "", "not json", "{broken", json.dumps({"verdicts": {}}),
                                  json.dumps({"verdicts": {**GOOD["verdicts"], "valuation": {"badge": "b"}}})])
def test_parse_narrative_rejects_incomplete(text):
    assert report.parse_narrative(text) is None


def _payload_stub(monkeypatch):
    monkeypatch.setattr(report, "_payload", lambda code, as_of: {**EMPTY, "stock_id": code.split(".")[0]})


def test_report_html_caches_narrative_per_as_of(monkeypatch, tmp_path):
    _payload_stub(monkeypatch)
    calls = []

    def gen(prompt):
        calls.append(prompt)
        return json.dumps(GOOD)

    for _ in range(2):
        html = report.report_html("3324.two", narrative=True, generate=gen, cache_dir=tmp_path)
    assert len(calls) == 1 and "資料包" in calls[0]
    assert "四維度總覽" in html and "AI 解讀產生失敗" not in html
    assert (tmp_path / "3324_2026-08-28.json").exists()


@pytest.mark.parametrize("gen", [lambda p: "抱歉無法回答", lambda p: (_ for _ in ()).throw(RuntimeError("down"))])
def test_report_html_llm_failure_degrades_to_numbers(monkeypatch, tmp_path, gen):
    _payload_stub(monkeypatch)
    html = report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    assert "AI 解讀產生失敗" in html and "四維度總覽" not in html
    assert not list(tmp_path.iterdir())      # 失敗不寫快取


@pytest.mark.parametrize("code", ["AAPL", "3324", "600519.SH", "３３２４.TW"])
def test_report_html_rejects_non_tw_codes(monkeypatch, code):
    _payload_stub(monkeypatch)
    with pytest.raises(report.UnsupportedMarket):
        report.report_html(code)


def test_dossier_endpoint_maps_errors(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.v1.endpoints.stocks import router

    real = report.report_html

    def boom(code, **kw):
        if code == "3324.TWO":
            raise ValueError("pandas parse error deep in build()")
        return real(code, **kw)

    monkeypatch.setattr(report, "report_html", boom)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/stocks")
    client = TestClient(app)
    r = client.get("/api/v1/stocks/AAPL/dossier")
    assert r.status_code == 400 and r.json()["detail"]["error"] == "unsupported_market"
    r = client.get("/api/v1/stocks/3324.TWO/dossier")
    assert r.status_code == 503 and r.json()["detail"]["error"] == "dossier_unavailable"
    assert client.get("/api/v1/stocks/2330.TW/dossier", params={"date": "２０２６-08-28"}).status_code == 422


def test_report_html_theme_attr(monkeypatch):
    _payload_stub(monkeypatch)
    assert '<html lang="zh-Hant" data-theme="dark">' in report.report_html("2330.TW", theme="dark")
    assert '<html lang="zh-Hant"><head>' in report.report_html("2330.TW", theme="evil\"><script>")


def test_unverified_numbers_flags_only_numbers_missing_from_payload():
    p = {**EMPTY, "valuation": {"pe": 26.29, "as_of": "2026-08-28"}, "smc": {"price": 1375.0, "fib": {"position": 0.128}}}
    nar = {"verdicts": {"valuation": {"note": "本益比 26.29 倍，現價 1,375.0，Fib 12.8%；外資持股 41.27%。"}},
           "notes": {"valuation": "以 EPS 自算本益比約 31.4 倍。"}}
    assert report.unverified_numbers(nar, p) == ["41.27"]


def test_unverified_numbers_accepts_fib_constants_and_unit_conversions():
    p = {**EMPTY, "fundamentals": {"monthly_revenue": [{"revenue_k": 3770000}], "quarters": []}}
    nar = {"notes": {"technical": "回撤到 0.618 與 0.705 之間（61.8%~70.5%），0.786 失守再看 50.0%。",
                     "revenue": "月營收 37.7 億（377,000 萬）。"}}
    assert report.unverified_numbers(nar, p) == []


def test_level_distances_count_only_as_percentages():
    # 正式站 6191／3324 的解讀都被標黃，抓到的全是「距現價 -2.94%」這類距離；報告的價位階梯本來就印這些數
    p = {**EMPTY, "smc": {"price": 1360.0, "ssl": [1320.0], "swing_n": 3,
                          "last_event": {"level": 1395.0, "i": 261},
                          "order_blocks": [{"low": 1240.0, "high": 1365.0}]},
         "chips": {"branch": {"five_sessions": {"avg_buy_cost": 1410.15}}}}
    ok = {"notes": {"technical": "1,320 的賣方流動性約 -2.94%，1,395 在上方 +2.57%，現價在其下 2.51%，"
                                 "OB 下緣 1,240 距 -8.82%；主力成本 1,410.15，現價低 3.56%。"}}
    assert report.unverified_numbers(ok, p) == []
    # 同一個數字沒寫「%」不算距離；也不能拿非價位欄位（K 棒序號 261、擺動點 3）去湊
    wrong = {"notes": {"technical": "賣方流動性約 2.94 元；距離 80.81%；距離 99.78%。"}}
    assert report.unverified_numbers(wrong, p) == ["2.94", "80.81", "99.78"]


def test_converted_amounts_must_carry_their_unit():
    # 3,765,466 千元：寫成 37.7 億、376.5 萬才算對；同一個數字配錯單位（或沒寫單位）差了十萬倍，要抓出來
    p = {**EMPTY, "fundamentals": {"monthly_revenue": [{"revenue_k": 3765466}], "quarters": []}}
    ok = {"notes": {"revenue": "7 月營收 37.7 億；換算 376,546.6 萬；原值 3,765,466 千元。"}}
    assert report.unverified_numbers(ok, p) == []
    wrong = {"notes": {"revenue": "7 月營收 37.7 千元；7 月營收 376,546.6 億；7 月營收 37.7。"}}
    assert report.unverified_numbers(wrong, p) == ["37.7", "376,546.6", "37.7"]


def test_legacy_cache_without_check_version_is_regenerated(monkeypatch, tmp_path):
    # 舊版核對規則寫的快取：當過期重寫，不能一直沿用
    _payload_stub(monkeypatch)
    calls = []

    def gen(prompt):
        calls.append(prompt)
        return json.dumps(GOOD)

    legacy = tmp_path / "3324_2026-08-28.json"
    legacy.write_text(json.dumps({**GOOD, "notes": {"valuation": "本益比 2,345.0"}}), encoding="utf-8")
    report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    assert len(calls) == 1
    assert json.loads(legacy.read_text(encoding="utf-8"))["check_version"] == report.NARRATIVE_CHECK_VERSION
    report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    assert len(calls) == 1      # 新版快取照常沿用


def test_cache_is_rewritten_when_same_day_data_changes(monkeypatch, tmp_path):
    # 同一基準日先開過一次，之後法人才入庫：資料包換了，解讀不能繼續引用舊數字
    calls = []

    def gen(prompt):
        calls.append(prompt)
        return json.dumps(GOOD)

    p = {**EMPTY, "chips": {"institutional": {"as_of": "2026-08-27"}}}
    report.cached_narrative(p, gen, tmp_path)
    report.cached_narrative(p, gen, tmp_path)
    assert len(calls) == 1
    report.cached_narrative({**p, "chips": {"institutional": {"as_of": "2026-08-28"}}}, gen, tmp_path)
    assert len(calls) == 2


def test_cache_is_rewritten_when_branch_arrives_or_a_section_recovers(tmp_path):
    calls = []

    def gen(prompt):
        calls.append(prompt)
        return json.dumps(GOOD)

    p = {**EMPTY, "chips": {"branch": {"day": None, "five_sessions": None}}, "errors": ["合約負債"]}
    report.cached_narrative(p, gen, tmp_path)
    report.cached_narrative(p, gen, tmp_path)
    assert len(calls) == 1
    with_branch = {**p, "chips": {"branch": {"day": {"buy": []}, "five_sessions": None}}}
    report.cached_narrative(with_branch, gen, tmp_path)          # 分點晚到
    assert len(calls) == 2
    report.cached_narrative({**with_branch, "errors": []}, gen, tmp_path)    # 失敗的段落這次讀到了
    assert len(calls) == 3
    report.cached_narrative({**with_branch, "errors": []}, gen, tmp_path)
    assert len(calls) == 3
    # 反方向（這次分點反而沒拿到）不重寫，沿用較完整的舊解讀
    report.cached_narrative({**p, "errors": []}, gen, tmp_path)
    assert len(calls) == 3


@pytest.mark.parametrize("path", [
    ("fundamentals", "monthly_revenue"), ("fundamentals", "quarters"), ("chips", "institutional"),
    ("chips", "margin"), ("chips", "holding"), ("valuation",), ("smc",),
])
def test_data_stamp_changes_with_every_cited_section(path):
    base = {"fundamentals": {"monthly_revenue": [{"month": "2026-08"}], "quarters": [{"quarter": "2026Q2"}]},
            "chips": {k: {"as_of": "2026-10-21"} for k in ("institutional", "margin", "holding")},
            "valuation": {"as_of": "2026-10-21"}, "smc": {"price": 100.0}}
    changed = json.loads(json.dumps(base))
    node = changed
    for k in path[:-1]:
        node = node[k]
    leaf = node[path[-1]]
    if isinstance(leaf, list):
        leaf.append({"month": "2026-09", "quarter": "2026Q3"})
    elif "as_of" in leaf:
        leaf["as_of"] = "2026-10-22"
    else:
        leaf["price"] = 101.0
    assert report.data_stamp(changed) != report.data_stamp(base)
    assert report.data_stamp(json.loads(json.dumps(base))) == report.data_stamp(base)


def test_incomparable_coverage_does_not_flip_flop(tmp_path):
    # 「分點有、合約負債失敗」與「分點逾時、各段都讀到」互相比不出誰完整：交替出現時不能每次都重寫
    calls = []

    def gen(prompt):
        calls.append(prompt)
        return json.dumps(GOOD)

    a = {**EMPTY, "chips": {"branch": {"day": {"buy": []}}}, "errors": ["合約負債"]}
    b = {**EMPTY, "chips": {"branch": {"day": None, "five_sessions": None}}, "errors": []}
    for p in (b, a, b, a, b, a):
        report.cached_narrative(p, gen, tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["garbage", "raises"])
def test_failed_rewrite_keeps_the_cached_narrative(tmp_path, failure):
    p = {**EMPTY, "chips": {"branch": {"day": None, "five_sessions": None}}}
    first = report.cached_narrative(p, lambda prompt: json.dumps(GOOD), tmp_path)

    def bad(prompt):
        if failure == "raises":
            raise RuntimeError("LLM down")
        return "not json"

    later = {**p, "chips": {"branch": {"day": {"buy": []}}}}      # 分點晚到，想重寫但 LLM 失敗
    assert report.cached_narrative(later, bad, tmp_path) == first
    # 數字本身變了（data_stamp 不同）時舊解讀不能拿來頂：照常回報失敗
    changed = {**later, "valuation": {"as_of": "2026-08-29"}}
    if failure == "raises":
        with pytest.raises(RuntimeError):
            report.cached_narrative(changed, bad, tmp_path)
    else:
        assert report.cached_narrative(changed, bad, tmp_path) is None


def test_written_unit_must_be_the_converted_value():
    # 「3,765,466 億」數字等於千元原值，但單位差了十萬倍
    p = {**EMPTY, "fundamentals": {"monthly_revenue": [{"revenue_k": 3765466}], "quarters": []}}
    assert report.unverified_numbers({"notes": {"revenue": "營收 3,765,466 億。"}}, p) == ["3,765,466"]
    assert report.unverified_numbers({"notes": {"revenue": "營收 3,765,466 千元，約 37.7 億。"}}, p) == []


def test_unverified_numbers_flags_decimal_slips_on_price_and_pe():
    # 單位換算只套在帶單位的欄位：價格、PE 小數點抄錯位要被抓到
    p = {**EMPTY, "valuation": {"pe": 23.45}, "smc": {"price": 1085.0}}
    nar = {"notes": {"valuation": "現價 108.5；現價 10.85；本益比 2.345；本益比 234.5；現價 1,085.0，本益比 23.45。"}}
    assert report.unverified_numbers(nar, p) == ["108.5", "10.85", "2.345", "234.5"]


def _chip_payload():
    # 2330 的真實數字（2026-10-22 資料包）
    return {**EMPTY, "chips": {"institutional": {"foreign_20d_lots": -149121, "foreign_5d_lots": -60094},
                               "margin": {"margin_balance": 35330, "margin_chg_5": -2140, "short_balance": 412},
                               "holding": {"total_holders": 3098860}, "branch": None},
            "smc": {"price": 1375.0}}


def test_lots_and_holders_may_be_written_in_wan():
    # 張數、人數照中文財經慣例寫成「萬張」「萬人」不能被當成核對不到（看板結論卡會因此消失）
    ok = {"notes": {"chips": "外資近 20 日賣超約 14.9 萬張，近 5 日賣超 6.0 萬張；融資餘額 3.53 萬張，"
                             "5 日減 0.21 萬張；總股東人數約 309.9 萬人；外資 20 日賣超 149,121 張。"}}
    assert report.unverified_numbers(ok, _chip_payload()) == []


def test_wan_conversion_needs_the_unit_and_stays_off_prices():
    p = _chip_payload()
    # 換算後的數字沒寫「萬」、寫成「億」、原值配「萬」都差了一萬倍；價格不准換成萬
    wrong = {"notes": {"chips": "外資賣超 14.9 張；外資賣超 14.9 億張；外資賣超 149,121 萬張；"
                                "總股東 309.9 人；現價 0.14 萬；現價 0.1375 萬。"}}
    assert report.unverified_numbers(wrong, p) == ["14.9", "14.9", "149,121", "309.9", "0.14", "0.1375"]


def _branch_payload():
    # 2330 的真實分點數字（2026-10-22 資料包）
    row = {"branch": "某分點", "buy": 120.0, "sell": 14450.0, "net": 14330.0, "share_pct": 1.23}
    return {**EMPTY, "chips": {"institutional": None, "margin": None, "holding": None,
                               "branch": {"day": None, "five_sessions": {
                                   "buy": [{"branch": "甲", "buy": 9000.0, "sell": 100.0, "net": 8900.0,
                                            "share_pct": 2.5}],
                                   "sell": [row], "buy_total": 16853.0, "sell_total": 60478.0,
                                   "avg_buy_cost": None, "avg_sell_cost": None}}},
            "smc": {"price": 1375.0},
            # 分點以外同名的 net／buy 欄位不能跟著換算（名稱太通用）
            "valuation": {"net": 25000.0, "buy": 31000.0}}


def test_branch_lots_may_be_written_in_wan():
    ok = {"notes": {"chips": "近五日分點賣出合計 6.05 萬張。最大賣超分點 5 日賣超 1.43 萬張。"
                             "近五日分點買進合計 1.69 萬張；該分點賣出 1.445 萬張；買超分點淨買 0.89 萬張。"}}
    assert report.unverified_numbers(ok, _branch_payload()) == []


def test_branch_wan_conversion_needs_the_unit_and_stays_inside_branch():
    wrong = {"notes": {"chips": "賣出合計 6.05 張；賣超 1.43 億張；占比 0.0123 萬；"
                                "別段的 net 2.5 萬；別段的 buy 3.1 萬。"}}
    assert report.unverified_numbers(wrong, _branch_payload()) == ["6.05", "1.43", "0.0123", "2.5", "3.1"]


def test_corrupt_narrative_cache_self_heals(monkeypatch, tmp_path):
    # 寫到一半被殺留下截斷的 JSON：要重呼 LLM 蓋掉它，不能整個基準日都顯示「AI 解讀產生失敗」
    _payload_stub(monkeypatch)
    cached = tmp_path / "3324_2026-08-28.json"
    calls = []

    def gen(prompt):
        calls.append(prompt)
        return json.dumps(GOOD)

    for broken in ('{"verdicts": {"fundamental": ', "[1, 2]", b"\xff\xfe\x00"):
        calls.clear()
        if isinstance(broken, bytes):
            cached.write_bytes(broken)
        else:
            cached.write_text(broken, encoding="utf-8")
        html = report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
        assert len(calls) == 1 and "AI 解讀產生失敗" not in html and "四維度總覽" in html
        assert json.loads(cached.read_text(encoding="utf-8"))["check_version"] == report.NARRATIVE_CHECK_VERSION
        # 重寫後的快取正常沿用，不會每次開都重付 LLM
        report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
        assert len(calls) == 1


def test_narrative_cache_write_is_atomic(monkeypatch, tmp_path):
    # 寫入途中失敗（被殺、磁碟滿）時舊快取保持完整，也不留下暫存檔
    p = {**EMPTY}
    first = report.cached_narrative(p, lambda prompt: json.dumps(GOOD), tmp_path)
    cached = tmp_path / "9999_2026-08-28.json"
    before = cached.read_text(encoding="utf-8")
    real_write = report.Path.write_text

    def dies_midway(self, text, *a, **k):
        real_write(self, text[:10], *a, **k)
        raise OSError("No space left on device")

    monkeypatch.setattr(report.Path, "write_text", dies_midway)
    changed = {**p, "valuation": {"as_of": "2026-08-29"}}      # 數字變了，要重寫
    with pytest.raises(OSError):
        report.cached_narrative(changed, lambda prompt: json.dumps(GOOD), tmp_path)
    assert cached.read_text(encoding="utf-8") == before
    assert [f.name for f in tmp_path.iterdir()] == [cached.name]
    assert json.loads(before) == first


def _bad_gen(calls):
    bad = {**GOOD, "notes": {"chips": "外資持股 41.27%。"}}

    def gen(prompt):
        calls.append(prompt)
        return json.dumps(bad, ensure_ascii=False)
    return gen


def _age(path, seconds):
    import os
    import time

    t = time.time() - seconds
    os.utime(path, (t, t))


def test_unverified_narrative_is_cached_with_notice_for_six_hours(monkeypatch, tmp_path):
    _payload_stub(monkeypatch)
    calls = []
    gen = _bad_gen(calls)
    html = report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    assert "四維度總覽" in html and "41.27" in html and "無法在資料包核對" in html
    cached = tmp_path / "3324_2026-08-28.json"
    assert json.loads(cached.read_text(encoding="utf-8"))["unverified"] == ["41.27"]
    _age(cached, 6 * 3600 - 60)
    html = report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    assert len(calls) == 1 and "無法在資料包核對" in html      # 6 小時內沿用快取，提示照樣出現


def test_unverified_narrative_is_regenerated_after_six_hours(monkeypatch, tmp_path):
    _payload_stub(monkeypatch)
    calls = []
    gen = _bad_gen(calls)
    report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    _age(tmp_path / "3324_2026-08-28.json", 6 * 3600 + 60)
    report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    assert len(calls) == 2


def test_verified_narrative_cache_does_not_expire_within_as_of(monkeypatch, tmp_path):
    _payload_stub(monkeypatch)
    calls = []

    def gen(prompt):
        calls.append(prompt)
        return json.dumps(GOOD)

    report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    _age(tmp_path / "3324_2026-08-28.json", 2 * 86400)
    report.report_html("3324.TWO", narrative=True, generate=gen, cache_dir=tmp_path)
    assert len(calls) == 1


def _seed_expired_payload(monkeypatch):
    from src.services import tw_stock_dossier

    monkeypatch.setattr(report, "_payload_cache", {("OLD.TW", None): (-1e9, {})})
    monkeypatch.setattr(tw_stock_dossier, "build", lambda code, as_of=None: {"stock_id": code})


def test_payload_cache_eviction_is_thread_safe(monkeypatch):
    """另一條請求在清理途中插進來：沒鎖時兩邊都刪同一個過期 key -> KeyError（API 回 503）。"""
    import threading

    _seed_expired_payload(monkeypatch)
    cache, errors, other = report._payload_cache, [], []

    class Racy(dict):
        def __delitem__(self, k):
            if not other:      # 第一次刪除前，讓另一條執行緒跑完整個 _payload
                t = threading.Thread(target=lambda: report._payload("B.TW", None))
                other.append(t)
                t.start()
                t.join(0.3)
            super().__delitem__(k)

    monkeypatch.setattr(report, "_payload_cache", Racy(cache))
    try:
        assert report._payload("A.TW", None) == {"stock_id": "A.TW"}
    except KeyError as exc:
        errors.append(exc)
    other[0].join(30)
    assert not errors and set(report._payload_cache) == {("A.TW", None), ("B.TW", None)}


def test_payload_build_runs_outside_cache_lock(monkeypatch):
    from src.services import tw_stock_dossier

    _seed_expired_payload(monkeypatch)
    held = []
    monkeypatch.setattr(tw_stock_dossier, "build",
                        lambda code, as_of=None: held.append(report._payload_lock.locked()) or {})
    report._payload("A.TW", None)
    assert held == [False]      # 慢的 build() 不能卡住其他代號的快取查詢


def test_failed_sections_are_listed_in_notice(monkeypatch):
    monkeypatch.setattr(report, "_payload", lambda code, as_of: {**EMPTY, "errors": ["估值", "技術面"]})
    assert "讀取失敗、以「無資料」呈現的段落：估值、技術面" in report.report_html("2330.TW")


def test_llm_generate_tags_usage_as_stock_dossier(monkeypatch):
    from src import analyzer as analyzer_mod

    seen = {}

    class FakeAnalyzer:
        def __init__(self, config):
            pass

        def is_available(self):
            return True

        def generate_text(self, prompt, **kw):
            seen.update(kw)
            return "{}"

    monkeypatch.setattr(analyzer_mod, "GeminiAnalyzer", FakeAnalyzer)
    report._llm_generate("x")
    assert seen["call_type"] == "stock_dossier"
    # 推理模型的推理也算在 max_tokens 裡：4096 在 NAS 上回空
    assert seen["max_tokens"] >= 8192


def test_generate_text_persists_given_call_type(monkeypatch):
    from unittest.mock import patch

    from src.analyzer import GeminiAnalyzer

    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    with patch.object(analyzer, "_call_litellm", return_value=("ok", "m", {"total_tokens": 1})), \
         patch("src.analyzer.should_persist_usage_telemetry", return_value=True), \
         patch("src.analyzer.persist_llm_usage") as persist:
        assert analyzer.generate_text("p") == "ok"
        assert analyzer.generate_text("p", call_type="stock_dossier") == "ok"
    assert [c.kwargs["call_type"] for c in persist.call_args_list] == ["market_review", "stock_dossier"]


def test_main_creates_missing_output_dirs(tmp_path):
    # skill／docs 寫的 -o reports/dossier/... 在乾淨 checkout 沒有這個目錄
    data = tmp_path / "data.json"
    data.write_text(json.dumps(EMPTY), encoding="utf-8")
    out = tmp_path / "reports" / "dossier" / "9999_2026-08-28.html"
    report.main(["9999", "--data", str(data), "-o", str(out)])
    assert out.is_file() and "<html" in out.read_text(encoding="utf-8").lower()
    dump = tmp_path / "nested" / "dump" / "9999.json"
    report.main(["9999", "--data", str(data), "--dump-data", str(dump)])
    assert json.loads(dump.read_text(encoding="utf-8"))["stock_id"] == "9999"
