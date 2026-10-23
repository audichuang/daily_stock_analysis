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
