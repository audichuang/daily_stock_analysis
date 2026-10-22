import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import tw_media_picks as mp  # noqa: E402

INDEX = [("3044.TW", "健鼎", []), ("6811.TWO", "宏碁資訊", []), ("0050.TW", "元大台灣50", ["台50"]),
         ("3374.TWO", "精材", []), ("2330.TW", "台積電", []),
         ("1111.TW", "某某電子", []), ("00981A.TW", "主動統一台股增長", []),
         ("00927.TW", "群益半導體收益", []), ("00929.TW", "復華台灣科技優息", []),
         ("00631L.TW", "元大台灣50正2", []), ("00850.TW", "元大臺灣ESG永續", []),
         ("6658.TW", "聯策", []), ("6438.TW", "迅得", []),
         ("6668.TW", "中揚光", []), ("00668.TW", "國泰美國道瓊", []), ("1303.TW", "南亞", []),
         ("0052.TW", "富邦科技", []), ("3029.TW", "零壹", [])]


def test_parse_answer_strips_fences_and_citations():
    text = '好的：\n```json\n[{"name": "健鼎", "stance": "bullish", "reason": "營收創高 [3, 5]"}, {"code": "x"}]\n```'
    picks = mp.parse_answer(text)
    assert picks == [{"name": "健鼎", "stance": "bullish", "reason": "營收創高"}]


def test_parse_answer_garbage_is_none_but_empty_list_is_no_picks():
    assert mp.parse_answer("沒有點名任何個股") is None
    assert mp.parse_answer("[not json]") is None
    assert mp.parse_answer("[]") == []


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
    assert mp.resolve("迅得", "6438", INDEX, said="6658 連測") == ("6658.TW", "code")
    assert mp.resolve("富邦科技", "0052", INDEX, said="52") == ("0052.TW", "code")
    # a misheard number that matches nothing falls back to the name / LLM code
    assert mp.resolve("元大台灣50", "0050", INDEX, said="5000") == ("0050.TW", "exact")
    assert mp.resolve("零壹", "3029", INDEX, said="01") == ("3029.TW", "exact")
    # fragments of spaced transcripts are not codes
    assert mp.resolve("中揚光", "6668", INDEX, said="668 中 陽 光") == ("6668.TW", "exact")
    assert mp.resolve("南亞", "1303", INDEX, said="130 連 南亞") == ("1303.TW", "exact")
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


def test_new_episodes_filters_and_stops_at_first_old_video(monkeypatch):
    listing = "\n".join([
        "new1\t3000\t【節目】今天完整版",
        "clip\t300\t【節目】今天片段",          # too short
        "done\t3000\t【節目】已處理完整版",      # already in journal
        "old1\t3000\t【節目】前天完整版",
        "old2\t3000\t【節目】更早完整版",
    ])
    dates = {"new1": "20261021",  # exactly on --since: included
             "old1": "20261019", "old2": "20261018"}
    asked = []

    def fake_run(cmd, timeout=600):
        if "--flat-playlist" in cmd:
            return listing
        vid = cmd[-1].rsplit("=", 1)[1]
        asked.append(vid)
        return dates[vid]

    monkeypatch.setattr(mp, "_run", fake_run)
    monkeypatch.setattr(mp, "CHANNELS", [("節目", "tv", "UCx", r"完整版", 1200)])
    eps = mp.new_episodes(mp.date(2026, 10, 21), {"done"})
    assert [e["video_id"] for e in eps] == ["new1"]
    assert eps[0]["kind"] == "tv"
    # newest-first tab: stop at the first old video instead of fetching every date
    assert asked == ["new1", "old1"]


def test_nb_retries_timeouts_and_errors(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        if len(calls) == 2:
            return SimpleNamespace(returncode=1, stdout='{"error": true, "message": "rate limited"}', stderr="")
        return SimpleNamespace(returncode=0, stdout='{"answer": "[]"}', stderr="")

    monkeypatch.setattr(mp.subprocess, "run", fake_run)
    monkeypatch.setattr(mp.time, "sleep", lambda s: None)
    assert mp.nb("ask", "q") == {"answer": "[]"}
    assert len(calls) == 3


def test_nb_gives_up_after_attempts(monkeypatch):
    import subprocess

    def always_timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(mp.subprocess, "run", always_timeout)
    monkeypatch.setattr(mp.time, "sleep", lambda s: None)
    try:
        mp.nb("ask", "q", attempts=2)
    except RuntimeError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
