# -*- coding: utf-8 -*-
"""scripts/media_picks_summary.py：覆核結論回灌、立場表、缺 date 的歷史列、CLI 必選輸出旗標。"""
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("media_picks_summary", ROOT / "scripts" / "media_picks_summary.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

SINCE = datetime.fromisoformat("2026-10-26T23:00:00+08:00")
NOW = "2026-10-26T23:20:00+08:00"
BEFORE = "2026-10-20T23:20:00+08:00"


def _pick(**kw):
    row = {"video_id": "v1", "show": "錢線百分百", "kind": "tv", "name": "台積電", "name_said": "台積電",
           "stock_code": "2330.TW", "resolve": "exact", "code_llm": "2330", "stance": "bullish",
           "speaker": "張三", "data": None, "date": "2026-10-26", "extracted_at": NOW}
    row.update(kw)
    return row


def _verdict(row, verdict, corrected=None):
    return {"video_id": row["video_id"], "show": row["show"], "name_said": row["name_said"],
            "stock_code": row["stock_code"], "verdict": verdict, "corrected_code": corrected,
            "reason": "x", "reviewed_at": NOW}


def _write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def index_path(tmp_path):
    p = tmp_path / "stocks.index.json"
    p.write_text(json.dumps([["1326.TW", "1326.TW", "台化", "th"], ["2330.TW", "2330.TW", "台積電", "tsmc"]]),
                 encoding="utf-8")
    return p


def _run(tmp_path, index_path, media, review=()):
    _write(tmp_path / "media-picks.jsonl", media)
    _write(tmp_path / "ptt-picks.jsonl", [])
    _write(tmp_path / "media-picks-review.jsonl", review)
    return mod.summarize(SINCE, journal_dir=tmp_path, transcript_dir=tmp_path / "tr", stock_index=index_path)


def _codes(s):
    return {st["code"]: st for st in s["stocks"]}


UNRES = dict(name="台化", name_said="台花", stock_code=None, resolve="unresolved", code_llm=None)


def test_correct_unresolved_joins_corrected_code(tmp_path, index_path):
    r = _pick(**UNRES)
    s = _run(tmp_path, index_path, [r], [_verdict(r, "correct", "1326.TW")])
    st = _codes(s)["1326.TW"]
    assert st["name"] == "台化"  # 來自注入的索引，不是 name_said「台花」
    assert st["voices"][0]["corrected_from"] == mod.UNRESOLVED
    out = mod.stock_detail(s, "1326.TW")
    assert "張三" in out and "原未對到代號，覆核更正" in out
    assert s["review"][0]["stock_code"] is None and s["review"][0]["already_reviewed"] is True


def test_official_name_beats_name_said(tmp_path, index_path):
    r = _pick(**{**UNRES, "name": "亂寫"})
    s = _run(tmp_path, index_path, [r], [_verdict(r, "correct", "1326.TW")])
    assert _codes(s)["1326.TW"]["name"] == "台化"


def test_correct_moves_voice_off_wrong_code(tmp_path, index_path):
    wrong = _pick(name_said="台花", stock_code="2330.TW", resolve="code_mismatch")
    s = _run(tmp_path, index_path, [wrong], [_verdict(wrong, "correct", "1326.TW")])
    assert "2330.TW" not in _codes(s)
    v = _codes(s)["1326.TW"]["voices"][0]
    assert v["corrected_from"] == "2330.TW"
    assert "原對到 2330.TW，覆核更正" in mod.stock_detail(s, "1326.TW")
    assert s["review"][0]["stock_code"] == "2330.TW"


def test_not_stock_removes_voice(tmp_path, index_path):
    r = _pick()
    s = _run(tmp_path, index_path, [r], [_verdict(r, "not_stock")])
    assert s["stocks"] == []
    assert mod.stock_detail(s, "2330.TW") == "本輪沒有人點名 2330.TW"


@pytest.mark.parametrize("verdict", ["confirm", "unclear"])
def test_confirm_and_unclear_keep_row(tmp_path, index_path, verdict):
    r = _pick(resolve="fuzzy")
    # unclear 即使帶了 corrected_code 也不能當更正
    s = _run(tmp_path, index_path, [r], [_verdict(r, verdict, "1326.TW")])
    assert list(_codes(s)) == ["2330.TW"]
    assert _codes(s)["2330.TW"]["voices"][0]["corrected_from"] is None


def test_correct_with_empty_code_is_ignored(tmp_path, index_path):
    r = _pick()
    s = _run(tmp_path, index_path, [r], [_verdict(r, "correct", "")])
    assert list(_codes(s)) == ["2330.TW"]


def test_last_review_row_wins(tmp_path, index_path):
    r = _pick(**UNRES)
    s = _run(tmp_path, index_path, [r], [_verdict(r, "correct", "1326.TW"), _verdict(r, "not_stock")])
    assert s["stocks"] == []
    s = _run(tmp_path, index_path, [r], [_verdict(r, "not_stock"), _verdict(r, "correct", "1326.TW")])
    assert list(_codes(s)) == ["1326.TW"]


def test_review_with_other_key_does_not_apply(tmp_path, index_path):
    r = _pick(**UNRES)
    other = _pick(**UNRES, video_id="v2")
    # other 也在 journal 裡，迴圈才會真的跑；r 的鍵沒有結論，必須維持未對到
    s = _run(tmp_path, index_path, [r, other], [_verdict(other, "correct", "1326.TW")])
    assert [v["corrected_from"] for v in _codes(s)["1326.TW"]["voices"]] == [mod.UNRESOLVED]
    assert len(_codes(s)["1326.TW"]["voices"]) == 1


def test_correction_applies_to_prior_rows(tmp_path, index_path):
    old = _pick(**UNRES, video_id="v0", extracted_at=BEFORE, date="2026-10-20")
    now = _pick(stock_code="1326.TW", name="台化", name_said="台化", video_id="v9")
    s = _run(tmp_path, index_path, [old, now], [_verdict(old, "correct", "1326.TW")])
    h = _codes(s)["1326.TW"]["history"]
    assert h and h["first_named"] == "2026-10-20"


def test_correct_without_index_file_falls_back_to_name_said(tmp_path):
    r = _pick(**UNRES)
    s = _run(tmp_path, tmp_path / "missing.json", [r], [_verdict(r, "correct", "1326.TW")])
    assert _codes(s)["1326.TW"]["name"] == "台花"


def test_input_rows_not_mutated(tmp_path, index_path):
    r = _pick(**UNRES)
    rows = [r]
    out = mod._apply_reviews(rows, [_verdict(r, "correct", "1326.TW")], index_path)
    assert rows[0]["stock_code"] is None and "corrected_from" not in rows[0]
    assert out[0]["stock_code"] == "1326.TW"


def test_dateless_prior_row_does_not_crash(tmp_path, index_path):
    old = _pick(video_id="v0", extracted_at=BEFORE, date=None)
    now = _pick(video_id="v9")
    s = _run(tmp_path, index_path, [old, now])
    assert _codes(s)["2330.TW"]["history"]["first_named"] is None
    assert "首次 ?" in mod._index(s)
    assert "首次 ?" in mod.stock_detail(s, "2330.TW")


def test_dateless_prior_does_not_hide_dated_first_named(tmp_path, index_path):
    nodate = _pick(video_id="v0", extracted_at=BEFORE, date=None)
    dated = _pick(video_id="v1", extracted_at=BEFORE, date="2026-10-20")
    s = _run(tmp_path, index_path, [nodate, dated, _pick(video_id="v9")])
    assert _codes(s)["2330.TW"]["history"]["first_named"] == "2026-10-20"


def test_avoid_counts_as_bear_and_shows_avoid_label(tmp_path, index_path):
    s = _run(tmp_path, index_path, [_pick(stance="avoid")])
    st = _codes(s)["2330.TW"]
    assert (st["bull_voices"], st["bear_voices"], st["neutral_voices"]) == (0, 1, 0)
    assert "[避]" in mod.stock_detail(s, "2330.TW")
    assert "｜避｜" in mod._index(s)


def test_neutral_stance_counts_neutral(tmp_path, index_path):
    st = _codes(_run(tmp_path, index_path, [_pick(stance="neutral")]))["2330.TW"]
    assert (st["bull_voices"], st["bear_voices"], st["neutral_voices"]) == (0, 0, 1)


def test_cli_requires_an_output_flag():
    with pytest.raises(SystemExit) as e:
        mod.main(["--since", "2026-10-26T23:00:00+08:00"])
    assert e.value.code == 2
