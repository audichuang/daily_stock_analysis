"""問股對象判定：繁體問法、代碼＋名稱＋自由問句，以及無對象時不預設 A 股（fork）。"""

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.chat_object_decision import decide_chat_object  # noqa: E402
from src.agent.stock_scope import StockIdentity  # noqa: E402
from src.market_context import get_market_guidelines, get_market_role  # noqa: E402
from src.services.agent_chat_session_service import _stock_lookup  # noqa: E402


@pytest.fixture(scope="module")
def stock_lookup():
    return _stock_lookup()


def _decide(message, current_code, stock_lookup):
    registry, lookup = stock_lookup
    current = StockIdentity.from_code(current_code, registry) if current_code else None
    return decide_chat_object(message, current, registry, lookup)


def _target(decision):
    return decision.target.identity.stock_code if decision.target else None


@pytest.mark.parametrize("message, expected", [
    ("2330.TW 台積電現在價格多少？最近的技術面怎麼看？", "2330.TW"),
    ("00631L.TW 怎麼看", "00631L.TW"),
    ("AAPL 最近怎麼樣", "AAPL"),
    ("2330.TW 還能買嗎", "2330.TW"),
])
def test_single_target_in_free_question_is_confirmed(message, expected, stock_lookup):
    decision = _decide(message, None, stock_lookup)
    assert decision.kind == "confirm"
    assert _target(decision) == expected


def test_follow_up_naming_another_stock_switches(stock_lookup):
    decision = _decide("那 2317.TW 呢", "2330.TW", stock_lookup)
    assert (decision.kind, _target(decision)) == ("confirm", "2317.TW")


def test_mentioning_current_stock_keeps_it(stock_lookup):
    assert _decide("2330.TW 最近的消息呢", "2330.TW", stock_lookup).kind == "maintain"


def test_traditional_choice_question_is_a_comparison(stock_lookup):
    decision = _decide("2330.TW 和 2317.TW 哪個好", None, stock_lookup)
    assert decision.kind == "compare"
    assert [item.stock_code for item in decision.participants] == ["2330.TW", "2317.TW"]


def test_traditional_denial_does_not_switch(stock_lookup):
    # 「別看」要被認成否定；沒有繁簡折疊時會落到單一標的規則，被誤判成換股。
    assert _decide("別看 2317.TW", "2330.TW", stock_lookup).kind == "maintain"


def test_two_unrelated_stocks_without_comparison_ask_to_clarify(stock_lookup):
    assert _decide("2330.TW 2317.TW 最近怎麼樣", None, stock_lookup).kind == "clarify"


def test_uncertain_switch_is_not_confirmed(stock_lookup):
    assert _decide("要不要換成 2317.TW", "2330.TW", stock_lookup).kind != "confirm"


def test_no_target_prompt_does_not_assume_a_share():
    for lang in ("zh", "en"):
        role = get_market_role("", lang)
        guidelines = get_market_guidelines(None, lang)
        assert "A 股" not in role and "A-share" not in role
        assert "T+1" not in guidelines and "沪深交易所" not in guidelines and "Shanghai" not in guidelines
    assert get_market_role("", "zh") == "股票"


def test_explicit_codes_keep_their_market_role():
    assert get_market_role("600519", "zh") == " A 股"
    assert get_market_role("2330.TW", "zh") == "台股"
    assert get_market_role("AAPL", "zh") == "美股"
