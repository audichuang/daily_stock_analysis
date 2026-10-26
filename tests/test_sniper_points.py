# -*- coding: utf-8 -*-
"""parse_sniper_value 對 LLM 敘述句的解析（字串取自 2026-10-22 等日正式庫 dsa.analysis_history）。"""

import pytest

from src.utils.sniper_points import extract_sniper_points, parse_sniper_value

# 2345.TW：句首是條件式進場價，停損價在「停損於」之後
STOP_2345 = "停損位：如果在1,909.00元進場，以1倍ATR14（約6.88%，約131元）設定停損於1,778.00元。持股者以收盤跌破1,770.00元為減碼點，1,700.00元為最後防線。"
STOP_2345_SIMP = "止损位：如果在1,909.00元进场，以1倍ATR14（约6.88%，约131元）设定止损于1,778.00元。持股者以收盘跌破1,770.00元为减码点，1,700.00元为最后防线。"


@pytest.mark.parametrize("text", [STOP_2345, STOP_2345_SIMP])
def test_stop_loss_takes_stop_clause_after_conditional_entry(text):
    assert parse_sniper_value(text, "stop_loss") == 1778.0


# 句首就給持股停損價，後段才是條件式進場的停損：維持句首的價位
@pytest.mark.parametrize("text, expected", [
    ("停損位：持股跌破119.00元出場（約現價減1倍ATR14，ATR14約4.70%、約5.90元）；若在129.00元條件單進場，停損設在122.90元（進場價減1倍ATR14）", 119.0),
    ("止损位：持股跌破119.00元出场（约现价减1倍ATR14，ATR14约4.70%、约5.90元）；若在129.00元条件单进场，止损设在122.90元（进场价减1倍ATR14）", 119.0),
    ("停損位：1,760.00元（從1,880元買點扣掉約1倍ATR14 116元，約-6.4%）；若從1,800元進場，停損設在1,680.00元", 1760.0),
    ("止损位：1,760.00元（从1,880元买点扣掉约1倍ATR14 116元，约-6.4%）；若从1,800元进场，止损设在1,680.00元", 1760.0),
    ("停損位：持股者收盤跌破13.70元（約為14.40減1倍ATR14，ATR14約4.59%）就出場；如果在13.80元試單，停損設13.15元（1倍ATR14）", 13.7),
    ("停損位：持股者若股價跌破MA20約365.0元（收盤價計）應執行停損；空手者暫不進場。", 365.0),
    # 句首的「若」是持股條件、不是進場句
    ("停損位：持股者若跌破119.00元就出場；若在129.00元進場，停損設在122.90元", 119.0),
])
def test_stop_loss_keeps_leading_holder_stop(text, expected):
    assert parse_sniper_value(text, "stop_loss") == expected


# 欄位標籤後寫明沒有價位（正式庫原文，簡繁各一）
@pytest.mark.parametrize("text", [
    "理想買入點：暫不設定。需收盤站回 MA5 431.20 元、量比大於 1，且外資與投信同步買超，才考慮試單。",
    "理想买入点：暂不设定。需收盘站回 MA5 431.20 元、量比大于 1，且外资与投信同步买超，才考虑试单。",
    "理想買入點：暫不設定。收盤站回 161.60元（MA10）並放量，而且外資與投信同步買超後才重新評估",
    "理想買點：暫不買進；要等收盤站回14.85元（MA10）以上、量比大於1，且外資與投信同時買超，才考慮進場",
    "理想买点：暂不买进；要等收盘站回14.85元（MA10）以上、量比大于1，且外资与投信同时买超，才考虑进场",
    "理想買入點：暫不進場。條件式買點為收盤站回 337.90 元（MA5）且放量，外資與投信同步淨買超才成立。",
    "理想买入点：暂不进场。条件式买点为收盘站回 337.90 元（MA5）且放量，外资与投信同步净买超才成立。",
    "理想買入點：暫不建議買入。條件是收盤站上MA10 137.80元、量能放大，而且外資、投信轉為買超，才重新評估",
    "理想买入点：暂不建议买入。条件是收盘站上MA10 137.80元、量能放大，而且外资、投信转为买超，才重新评估",
    "理想買入點：暫不提供。需要站回並守穩 MA10 約1,755.00元，而且外資轉為買超，再考慮在1,755.00～1,770.00元區間小量",
    "理想買點：目前不建議進場。條件式買點是收盤站回 MA10（16,700.00元），量比大於1，且外資、投信同步買超。",
    "目前不建議買進。條件式觀察點：收盤站回 101.10 元（MA5），而且量比大於 1、外資與投信同步買超，才考慮小量試單",
    "暫不給買點。等收盤站穩 42.11（MA10）上方、MA5 重新站上 MA10，且量能溫和放大（量比約 1.2 以上），才評估試單。",
    "次要買入點：不設。站回MA5（1387.00元）仍在空頭排列中，不符合做多紀律，只當作轉強的初步觀察訊號。",
    "次要買點：不建議。若回測4165.00元附近量縮止穩，也只能列入觀察，不進場",
    "理想買入點：暫不適用（目前為空頭排列）。須收盤站穩 1511.50 元（MA20），且 MA5 上彎、法人轉為買超，才重新評估",
    "次優買入點：無。4870.00元附近止穩只列為觀察，不列為買點（空頭排列不承接下跌）",
    "N/A",
])
def test_labelled_not_set_is_none(text):
    assert parse_sniper_value(text, "ideal_buy") is None
    assert parse_sniper_value(text) is None


# 「不」字出現在句中或後接具體價位的建議，不算沒有價位
@pytest.mark.parametrize("text, expected", [
    ("理想買入點：1613.00 元（條件式。要收盤站回 MA5、量比大於 1，而且外資與投信同步買超才成立，目前不符合）", 1613.0),
    ("理想買點：不建議現價追買。若回測 262.0 元（今日低點）附近且量縮收腳", 262.0),
    ("暫不建議追高，回測500元附近再買", 500.0),
    ("回測1900元附近分批布局，跌破1850元暫不進場", 1900.0),
    ("理想買點：無明顯支撐，回測100元附近再評估", 100.0),
])
def test_not_set_only_when_leading(text, expected):
    assert parse_sniper_value(text, "ideal_buy") == expected


def test_buy_field_ignores_stop_clause():
    assert parse_sniper_value("理想買點：1,909.00元，而且要同時符合收盤站回MA5", "ideal_buy") == 1909.0
    assert parse_sniper_value("如果在1909元進場，停損設在1778元", "ideal_buy") == 1909.0
    assert parse_sniper_value("如果在1909元進場，停損設在1778元", None) == 1909.0


def test_take_profit_conditional_entry_uses_target_anchor():
    assert parse_sniper_value("目標位：若在1,909元進場，目標價2,100元", "take_profit") == 2100.0
    assert parse_sniper_value("目標位：2,080.00元。從1,909.00元進場計算約+8.96%", "take_profit") == 2080.0


def test_stop_field_ignores_target_anchor():
    text = "若在1,800元進場，停損設在1,700元，目標價2,100元"
    assert parse_sniper_value(text, "stop_loss") == 1700.0
    assert parse_sniper_value(text, "take_profit") == 2100.0


def test_plain_cases_unchanged():
    assert parse_sniper_value("建议在 100 元附近买入") == 100.0
    assert parse_sniper_value("價格：100.5元") == 100.5
    assert parse_sniper_value("停損於95元", "stop_loss") == 95.0
    # 無「元」的條件式句維持舊路徑（2421.TW 正式原文）
    assert parse_sniper_value("停損位：空手者若在160.00進場，停損設153.50（約1倍ATR14，約-4.06%）", "stop_loss") == 153.5


def test_extract_passes_field():
    class R:
        def get_sniper_points(self):
            return {"ideal_buy": "理想買入點：暫不設定。需收盤站回 MA5 431.20 元", "stop_loss": STOP_2345,
                    "take_profit": "目標位：2,080.00元", "secondary_buy": None}
    assert extract_sniper_points(R()) == {
        "ideal_buy": None, "secondary_buy": None, "stop_loss": 1778.0, "take_profit": 2080.0}


# 正式庫原文：「暫無買點」開頭、或「觀望，」之後才寫暫不設定，都是沒有價位（句內的 MA／括號價位不能被當成買點）
@pytest.mark.parametrize("text", [
    "暫無買點。待收盤站回 MA10 約 12.77 元再評估",
    "暂无买点。待收盘站回 MA10 约 12.77 元再评估",
    "理想買入點：暫無價位。待收盤站回 MA10 約 12.77 元再評估",
    "观望，暂不设定（161.6元）",
    "觀望，暫不設定（161.6元）",
    "理想買入點：觀望，暫不設定（161.6元）",
    "觀望，暫無買點，待站回MA10 161.6元",
])
def test_leading_no_buypoint_phrases_are_none(text):
    assert parse_sniper_value(text, "ideal_buy") is None
    assert parse_sniper_value(text) is None


# 反向：暫無／觀望之後仍是真實價位或條件，不能被吞掉
@pytest.mark.parametrize("text, expected", [
    ("暫無明顯支撐，回測100元附近再評估", 100.0),
    ("觀望，回測100元附近再評估", 100.0),
    ("觀望至收盤站回12.77元再評估，暫不追高", 12.77),
    ("觀望，回測100元附近再買，跌破95元暫不進場", 100.0),
])
def test_no_buypoint_phrases_do_not_overreach(text, expected):
    assert parse_sniper_value(text, "ideal_buy") == expected


# 2026-10-21 正式庫原文：暫不設定之後的 MA 價位不是買點（3211.TWO／2408.TW／6669.TW／2454.TW）
@pytest.mark.parametrize("text", [
    "理想買入點：暫不設定。收盤站回 MA10（360.05 元）、量能配合、MA5 翻揚之後才重新評估，目前不建議買進",
    "理想買入點：暫不設定；須等到放量站穩MA10 472.30元、MA5翻揚，且法人連續買超後，再以回測約472.00元不破為進場條件",
    "理想買入點：暫不建議買入。待股價帶量站回 MA10 2,050.50元、三大法人轉為買超後再評估",
    "理想買點：暫不設定。空頭排列不做多，等收盤站回MA10（4,406.00元）且MA5上彎後再重新評估",
])
def test_prod_1021_not_set_with_ma_price_is_none(text):
    assert parse_sniper_value(text, "ideal_buy") is None


# 2026-10-22／23 正式庫原文（dsa.analysis_history）：各種「沒有買點」的說法，句內的 MA／觀察價不是買點
@pytest.mark.parametrize("text", [
    "暫時無理想買點，需等待股價站穩MA5（約238.1元）且量能放大至5日均量以上。",  # 22
    "未出現買點，需等待站回MA10（241.8元）且量能放大",  # 42
    "暫無明確買點，等待站回MA5（約281.2元）且成交量放大至5日均量以上再評估",  # 116
    "暫無次優買點，若回測118元不破且量縮可小量試單。",  # 127
    "次優買點：暫時從缺；須先站回MA20(14.56元)並形成多頭排列後再重新評估。",  # 160
    "理想買入點：暫時無（需站穩 MA20 274.8 元以上且量能放大才考慮）",  # 178
    "尚無理想買點，需等股價站回MA20（120.3元）且量能溫和放大。",  # 254
    "暫時無理想買點；若後續放量站穩MA10（279.4元）且均線轉多頭，可於回踩MA5（約278.7元）不破時輕倉試單",  # 342
    "不建議於目前位置買進（未形成多頭排列）。觀察價：待收盤站回 MA5 368.2 元且量能放大後再評估。",  # 399
    "理想買點：暫時不成立。需先站回 MA5（493.90 元）並帶量收復，回測 493.90 元不破且三大法人轉為淨買超，才考慮第一筆試單。",  # 425
    "次優買入點：資料不支持在空頭排列下接刀，暫不設定；如果股價回測241.00元附近量縮止穩，只當作觀察訊號，不當買點",  # 796
    "理想買入點：目前不成立。須等收盤站回MA5 133.40元、法人轉買超，之後回測133.40元不破才考慮",  # 975
    "次優買入點：不建議在126.50元附近逆勢承接，僅作為觀察止跌的參考價位",  # 975
    "理想買點：目前空頭排列，不設主動買點。只有在45.00元附近止跌、量縮且不破低時，才考慮試單",  # 1005
    "暂时无理想买点，需等待股价站稳MA5（约238.1元）",
    "暂无次优买点，若回测118元不破",
    "尚无理想买点，需等股价站回MA20（120.3元）",
    "未出现买点，需等待站回MA10（241.8元）",
    "次优买点：暂时从缺；须先站回MA20(14.56元)",
    "理想买点：目前空头排列，不设主动买点。只有在45.00元附近止跌",
    "不建议于目前位置买进。观察价：待收盘站回 MA5 368.2 元",
    "次优买入点：资料不支持在空头排列下接刀，暂不设定；如果股价回测241.00元附近",
])
def test_prod_1022_not_set_wording_is_none(text):
    assert parse_sniper_value(text, "ideal_buy") is None
    assert parse_sniper_value(text, "secondary_buy") is None


# 反向：看起來像但後面是真實價位，必須保留（402／438／461 正式庫原文）
@pytest.mark.parametrize("text, expected", [
    ("理想買點：不建議現價追買。若回測 262.0 元（今日低點）附近且量縮收腳、外資轉為淨買超，可小量試單，參考價 262.5 元。", 262.0),
    ("不建議現價追，回測1659元再試單", 1659.0),
    ("不建議現價進場；若回踩 MA10 171.95 元附近縮量止穩，可小倉試探。", 171.95),
    ("理想買入點：1000元（條件成立才買）", 1000.0),
    ("12.5元（觀望，暫不設定）", 12.5),
    ("理想買入點：250.50元（只限收盤放量站回MA20 249.95元之上、隔日回測不破時才進場；目前條件未成立）", 250.5),
    ("暫無明顯支撐，回測100元附近再評估", 100.0),
    ("不建議在目前價位追高，回測100元附近再買", 100.0),
])
def test_prod_1022_wording_reverse_keeps_price(text, expected):
    assert parse_sniper_value(text, "ideal_buy") == expected


# Code review 重現的誤判：句首說沒有／不成立，但後面另給了這個欄位可執行的價位，必須保留
@pytest.mark.parametrize("text, field, expected", [
    ("理想買入點：從缺，回測118元可試單", "ideal_buy", 118.0),
    ("尚無理想買點，回測118.5元可試單", "ideal_buy", 118.5),
    ("暫無明確支撐，118元附近試單", "ideal_buy", 118.0),
    ("次優買入點：未出現買點前先觀察，站回125元再買", "secondary_buy", 125.0),
    ("不建議在126.5元附近承接，回測120元再買", "secondary_buy", 120.0),
    ("目標價：不成立則看130元", "take_profit", 130.0),
    ("目標價：不成立，暫看 120 元", "take_profit", 120.0),
    ("不成立則停損 90 元", "stop_loss", 90.0),
    ("空頭排列，不給目標價，反彈 110 元減碼", "take_profit", 110.0),
])
def test_not_set_prefix_keeps_later_actionable_price(text, field, expected):
    assert parse_sniper_value(text, field) == expected


# 反向：後面只是條件式重新評估價、被拒絕的價位或 MA 價，仍是沒有價位
@pytest.mark.parametrize("text, field", [
    ("暫時無理想買點，需站回 120 元再評估", "ideal_buy"),
    ("不建議在 126.50 元附近逆勢承接", "secondary_buy"),
    ("不建議在126.50元附近逆勢承接", "secondary_buy"),
    ("理想買入點：暫不設定。要等放量站回 MA5（360.70 元）而且 MA5 拐頭向上，才考慮在 361.00 元附近小量試單", "ideal_buy"),
    ("次優買入點：暫不設定。空頭排列中不在 MA5 875.80 元附近承接，也不在 864.00 元附近承接。", "secondary_buy"),
    ("次要買點：不建議。在空頭排列下回測MA5 242.70元附近承接，風險報酬比不到1", "secondary_buy"),
    ("理想買點：暫時不成立，站回120元才重新評估", "ideal_buy"),
    ("目標價：暫不設定。站回MA5 100元再評估", "take_profit"),
    ("停損：暫不設定", "stop_loss"),
])
def test_not_set_prefix_without_actionable_price_is_none(text, field):
    assert parse_sniper_value(text, field) is None


# Review round 2：句首沒有價位時，停損／停利只取「直接綁定該欄位動作」的價位本身，不回落到泛用解析的第一個數字
@pytest.mark.parametrize("text, field, expected", [
    ("暫不設定，現價125元，跌破118元停損", "stop_loss", 118.0),
    ("不給目標價，MA60 130元附近不追，反彈110元減碼", "take_profit", 110.0),
    ("暫不設定；季線130元壓力大，反彈至120元減碼", "take_profit", 120.0),
])
def test_sell_not_set_prefix_returns_action_bound_price(text, field, expected):
    assert parse_sniper_value(text, field) == expected


@pytest.mark.parametrize("text, field", [
    ("停利：暫不設定（現價 125 元已跌破均線）", "take_profit"),
    ("N/A（已出清，不再估算 130 元）", "take_profit"),
    ("暫不設定，近5日跌3.2元", "take_profit"),
    ("暫不設定，參考MA20(118元)", "stop_loss"),
    ("不設停損，若跌破前低118元再評估", "stop_loss"),
    ("不設停損，跌破118元再評估", "stop_loss"),
    ("暫不設定，不再看130元", "take_profit"),
])
def test_sell_not_set_prefix_without_action_bound_price_is_none(text, field):
    assert parse_sniper_value(text, field) is None


@pytest.mark.parametrize("text,field,expected", [
    # 買點用語（尚無／暫無明確／從缺／不成立）不作用在停損／停利，維持正式版取得到的價位
    ("尚無明確支撐，跌破前低118元", "stop_loss", 118.0),
    ("未出現明確買點，若持有跌破前低118元", "stop_loss", 118.0),
    ("暫無明確目標，反彈至前高150元", "take_profit", 150.0),
    ("暫時無明確目標價，上看前高150元", "take_profit", 150.0),
    ("暫無明確目標，先看前高150元", "take_profit", 150.0),
    ("從缺（建議以118元為停損）", "stop_loss", 118.0),
    ("暫不設定，持有者以118元作為停損", "stop_loss", 118.0),
    # 買點欄位仍用較寬的清單
    ("尚無理想買點，站回120元再評估", "ideal_buy", None),
    ("暫無明確買點", "ideal_buy", None),
])
def test_buy_only_not_set_words_do_not_touch_sell_fields(text, field, expected):
    assert parse_sniper_value(text, field=field) == expected


# 文字中的數字比例「1:1」不是欄位標籤冒號
@pytest.mark.parametrize("text, expected", [
    ("目標位：2,080.00元。風險報酬比勉強達到1:1。第一個壓力在MA10（1,978.50元）附近。", 2080.0),
    ("目標位：2,080.00元。風險報酬比勉強達到1：1。第一個壓力在MA10（1,978.50元）附近。", 2080.0),
    ("目標位：2,080.00元。風報比1比1。第一個壓力在MA10（1,978.50元）附近。", 2080.0),
    ("停利：2，080.00元", 2080.0),
    ("停利：2,080元", 2080.0),
])
def test_numeric_ratio_colon_is_not_field_label(text, expected):
    assert parse_sniper_value(text, "take_profit") == expected


@pytest.mark.parametrize("ma", ["MA5", "ma5", "Ma10"])
def test_letter_digit_colon_label_is_kept(ma):
    assert parse_sniper_value(f"現價125元，停損參考{ma}：118元", "stop_loss") == 118.0


@pytest.mark.parametrize("prefix", ["暫無", "暂无", "無", "无", "不建議", "不建议", "無明確買點", "无明确买点"])
@pytest.mark.parametrize("comma", ["，", ","])
@pytest.mark.parametrize("field", [None, "ideal_buy", "secondary_buy"])
def test_not_set_comma_is_preserved_before_reassessment_price(prefix, comma, field):
    assert parse_sniper_value(f"{prefix}{comma}站回125元再評估", field) is None


@pytest.mark.parametrize("text, expected", [
    ("暫無，站回1,250元再買", 1250.0),
    ("暂无,站回1，250元再买", 1250.0),
    ("暫無明顯支撐，回測100元附近再評估", 100.0),
    ("暫無，回測1,250元可試單", 1250.0),
])
def test_not_set_comma_fix_preserves_actionable_and_descriptive_prices(text, expected):
    assert parse_sniper_value(text, "ideal_buy") == expected


# 句首「暫無，」之後只剩重新評估條件：逗號不能先被濾掉，否則 _END 的逗號分支永遠比不到、把再評估價位當成買點
@pytest.mark.parametrize("text", [
    "暫無，站回125元再評估",
    "暂无，站回125元再评估",
    "理想買入點：暫無，站回125元再評估",
    "無，等站回125元再評估",
])
def test_not_set_followed_by_comma_is_none(text):
    assert parse_sniper_value(text, "ideal_buy") is None
    assert parse_sniper_value(text) is None


# 反向：「暫無，」之後真的給了這個欄位可執行的價位，仍要保留；千分位逗號照舊濾掉
@pytest.mark.parametrize("text, field, expected", [
    ("暫無，回測118元可試單", "ideal_buy", 118.0),
    ("暫無，跌破95元停損", "stop_loss", 95.0),
    ("暫無，站回1,250元再買", "ideal_buy", 1250.0),
    ("暫無明顯支撐，回測100元附近再評估", "ideal_buy", 100.0),
])
def test_not_set_followed_by_comma_keeps_actionable_price(text, field, expected):
    assert parse_sniper_value(text, field) == expected
