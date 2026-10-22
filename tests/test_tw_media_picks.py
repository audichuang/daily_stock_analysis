import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import tw_media_picks as mp  # noqa: E402

INDEX = [("3044.TW", "健鼎", []), ("6811.TWO", "宏碁資訊", []), ("0050.TW", "元大台灣50", ["台50"]),
         ("3374.TWO", "精材", []), ("2330.TW", "台積電", []),
         ("1111.TW", "某某電子", []), ("00981A.TW", "主動統一台股增長", []),
         ("00927.TW", "群益半導體收益", []), ("00929.TW", "復華台灣科技優息", []),
         ("00631L.TW", "元大台灣50正2", []), ("00850.TW", "元大臺灣ESG永續", [])]


def test_parse_answer_strips_fences_and_citations():
    text = '好的：\n```json\n[{"name": "健鼎", "stance": "bullish", "reason": "營收創高 [3, 5]"}, {"code": "x"}]\n```'
    picks = mp.parse_answer(text)
    assert picks == [{"name": "健鼎", "stance": "bullish", "reason": "營收創高"}]


def test_parse_answer_garbage_returns_empty():
    assert mp.parse_answer("沒有點名任何個股") == []
    assert mp.parse_answer("[not json]") == []


def test_resolve_order():
    assert mp.resolve("台積電公司", "2330", INDEX) == ("2330.TW", "code")
    # the name wins over a wrong code the LLM guessed
    assert mp.resolve("健鼎", "2330", INDEX) == ("3044.TW", "exact")
    assert mp.resolve("隨便", "2330", INDEX) == ("2330.TW", "code_mismatch")
    assert mp.resolve("臻鼎", None, [("4958.TW", "臻鼎-KY", [])]) == ("4958.TW", "exact")
    assert mp.resolve("健鼎", None, INDEX) == ("3044.TW", "exact")
    assert mp.resolve("台50", None, INDEX) == ("0050.TW", "alias")
    # misheard name with the correct one in parentheses
    assert mp.resolve("精綵（精材）", None, INDEX) == ("3374.TWO", "exact")
    assert mp.resolve("宏碁資訊（紅資訊/弘資訊）", None, INDEX) == ("6811.TWO", "exact")
    assert mp.resolve("台積", None, INDEX) == ("2330.TW", "fuzzy")
    assert mp.resolve("981A", "981A", INDEX) == ("00981A.TW", "code")
    # a number read out on air beats the ETF name the LLM filled in
    assert mp.resolve("復華台灣科技優息", "00927", INDEX, said="00927") == ("00927.TW", "code")
    assert mp.resolve("健鼎", None, INDEX, said="鑑頂") == ("3044.TW", "exact")
    assert mp.resolve("850", None, INDEX, said="850") == ("00850.TW", "code")
    # digits inside a nickname are not a code
    assert mp.resolve("元大台灣50正2", None, INDEX, said="0050正2") == ("00631L.TW", "exact")


def test_resolve_does_not_force_a_match():
    # homophones share no characters; difflib can't recover them, so they must stay unresolved
    assert mp.resolve("建頂", None, INDEX) == (None, "unresolved")
    assert mp.resolve("某某科技", None, INDEX) == (None, "unresolved")
    assert mp.resolve("某某科技", "9999", INDEX) == (None, "unresolved")


def test_already_done_reads_video_ids(tmp_path):
    p = tmp_path / "j.jsonl"
    p.write_text("\n".join(json.dumps({"video_id": v}) for v in ("a", "b")) + "\n", encoding="utf-8")
    assert mp.already_done(p) == {"a", "b"}
    assert mp.already_done(tmp_path / "missing.jsonl") == set()
