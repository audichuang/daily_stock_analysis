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
    return mod.summarize(SINCE, journal_dir=tmp_path, transcript_dir=tmp_path / "tr", stock_index=index_path,
                         logs_dir=tmp_path / "logs")


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


WRONG_DATA = {"as_of": "2026-10-26", "close": 999.0}


def test_corrected_row_drops_wrong_stock_data(tmp_path, index_path):
    wrong = _pick(name_said="台花", stock_code="2330.TW", resolve="code_mismatch", data=WRONG_DATA)
    s = _run(tmp_path, index_path, [wrong], [_verdict(wrong, "correct", "1326.TW")])
    assert _codes(s)["1326.TW"]["data"] is None
    assert "數據：無" in mod.stock_detail(s, "1326.TW")


def test_corrected_row_keeps_other_rows_data(tmp_path, index_path):
    wrong = _pick(name_said="台花", stock_code="2330.TW", resolve="code_mismatch", data=WRONG_DATA)
    good = _pick(video_id="v2", stock_code="1326.TW", name="台化", data={"as_of": "2026-10-26", "close": 50.0})
    s = _run(tmp_path, index_path, [wrong, good], [_verdict(wrong, "correct", "1326.TW")])
    assert _codes(s)["1326.TW"]["data"]["close"] == 50.0


def test_history_ignores_wrong_close_of_corrected_prior_row(tmp_path, index_path):
    old = _pick(video_id="v0", name_said="台花", stock_code="2330.TW", resolve="code_mismatch",
                extracted_at=BEFORE, date="2026-10-20", data={"as_of": "2026-10-20", "close": 999.0})
    now = _pick(video_id="v9", stock_code="1326.TW", name="台化", data={"as_of": "2026-10-26", "close": 50.0})
    s = _run(tmp_path, index_path, [old, now], [_verdict(old, "correct", "1326.TW")])
    h = _codes(s)["1326.TW"]["history"]
    assert h["first_named"] == "2026-10-20"
    assert h["first_close"] is None and h["since_first_pct"] is None


@pytest.mark.parametrize("verdict", ["confirm", "unclear"])
def test_confirm_unclear_keep_data(tmp_path, index_path, verdict):
    r = _pick(resolve="fuzzy", data={"as_of": "2026-10-26", "close": 900.0})
    s = _run(tmp_path, index_path, [r], [_verdict(r, verdict)])
    assert _codes(s)["2330.TW"]["data"]["close"] == 900.0


# ---- judge_since：上一輪判讀中斷時往前涵蓋 ----

def _t(day, hour=23):
    return datetime.fromisoformat(f"2026-10-{day:02d}T{hour:02d}:00:00+08:00")


CUR = _t(26)


def test_judge_since_without_since_in_verdicts_is_current():
    assert mod.judge_since(CUR, [{"code": "2330.TW"}], [_t(24), _t(25)]) == CUR
    assert mod.judge_since(CUR, [], [_t(25)]) == CUR


def test_judge_since_previous_round_judged_is_current():
    rows = [{"since": _t(25).isoformat()}]
    assert mod.judge_since(CUR, rows, [_t(24), _t(25), CUR]) == CUR


def test_judge_since_previous_round_interrupted_goes_back_to_it():
    rows = [{"since": _t(24).isoformat()}, {"code": "no-since"}]
    assert mod.judge_since(CUR, rows, [_t(23), _t(24), _t(25), CUR]) == _t(25)


def test_judge_since_uses_latest_since_not_row_order():
    rows = [{"since": _t(23).isoformat()}, {"since": _t(25).isoformat()}, {"since": _t(24).isoformat()}]
    assert mod.judge_since(CUR, rows, [_t(23), _t(24), _t(25)]) == CUR


def test_judge_since_excludes_rounds_older_than_max_days():
    rows = [{"since": _t(10).isoformat()}]
    assert mod.judge_since(CUR, rows, [_t(11), _t(18), _t(25)]) == _t(25)   # 11、18 超過 7 天
    assert mod.judge_since(CUR, rows, [_t(11)], max_days=30) == _t(11)
    assert mod.judge_since(CUR, rows, [_t(19)]) == _t(19)                    # 剛好 7 天算在內


def test_judge_since_ignores_rounds_after_current():
    rows = [{"since": _t(24).isoformat()}]
    assert mod.judge_since(CUR, rows, [_t(27), _t(28)]) == CUR


def test_round_sinces_ignores_malformed_lines(tmp_path):
    (tmp_path / "media_picks_job_a.log").write_text(
        "[x] RESULT since=2026-10-25T23:00:00+0800\nRESULT since=garbage\nRESULT since=\nnoise\n"
        "[y] RESULT since=2026-10-26T23:00:01+08:00 extra\n", encoding="utf-8")
    (tmp_path / "other.log").write_text("RESULT since=2026-10-01T00:00:00+0800\n", encoding="utf-8")
    assert mod.round_sinces(tmp_path) == [_t(25), datetime.fromisoformat("2026-10-26T23:00:01+08:00")]


def test_cli_judge_since_reads_journal_and_logs(tmp_path, capsys):
    _write(tmp_path / "media-picks-verdicts.jsonl", [{"code": "2330.TW", "since": _t(24).isoformat()}])
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "media_picks_job_1.log").write_text("RESULT since=2026-10-25T23:00:00+0800\n", encoding="utf-8")
    argv = ["--since", CUR.isoformat(), "--judge-since", "--journal-dir", str(tmp_path), "--logs-dir", str(logs)]
    assert mod.main(argv) == 0
    assert capsys.readouterr().out.strip() == _t(25).isoformat()
    with pytest.raises(SystemExit):
        mod.main(["--since", CUR.isoformat(), "--judge-since", "--json"])


def test_judge_since_catch_up_round_records_its_own_since():
    # 判斷列的 since 記「本輪」的 since（判到這輪為止），不是補判的起點；否則下一輪會把剛補判過的那輪再判一次
    rounds = [_t(23), _t(24), _t(25), CUR]
    rows = [{"since": _t(23).isoformat()}]                       # 23 號判過，24 號中斷
    assert mod.judge_since(_t(25), rows, rounds) == _t(24)        # 25 號補判 24 號
    rows.append({"since": _t(25).isoformat()})                    # 25 號寫下自己的 since
    assert mod.judge_since(CUR, rows, rounds) == CUR              # 26 號不再回頭


# ---- 首次至今 %：跨除權息／分割要用還原後的收盤 ----

def _px(close, factor=None, as_of="2026-10-23"):
    d = {"as_of": as_of, "close": close}
    return d if factor is None else d | {"cum_adj_factor": factor}


def test_since_first_uses_adjusted_closes_across_dividend_and_split(tmp_path, index_path):
    # 首次 100、之後配 5 元（因子 0.95）收 98：實際 +3.2%，不是 -2%；1 拆 4（因子 0.25）收 26：+4%，不是 -74%
    assert mod._since_first(_px(98, 0.95), _px(100, 1.0)) == (3.2, True)
    assert mod._since_first(_px(26, 0.25), _px(100, 1.0)) == (4.0, True)
    s = _run(tmp_path, index_path, [_pick(extracted_at=BEFORE, date="2026-10-20", data=_px(100, 1.0, "2026-10-20")),
                                    _pick(data=_px(98, 0.95))])
    h = _codes(s)["2330.TW"]["history"]
    assert (h["since_first_pct"], h["since_first_adjusted"]) == (3.2, True)
    assert "首次至今 +3.2%（2026-10-20 收 100）" in mod.stock_detail(s, "2330.TW")


def test_since_first_without_factor_falls_back_to_raw_and_says_so(tmp_path, index_path):
    # 反向：舊快照沒有 cum_adj_factor，不能亂套（也不能因此消失），照原始收盤算並標出未還原
    assert mod._since_first(_px(98, 0.95), _px(100)) == (-2.0, False)
    assert mod._since_first(_px(98), _px(100, 1.0)) == (-2.0, False)
    assert mod._since_first(_px(100, 1.0), _px(100, 1.0)) == (0.0, True)
    s = _run(tmp_path, index_path, [_pick(extracted_at=BEFORE, date="2026-10-20", data=_px(100, as_of="2026-10-20")),
                                    _pick(data=_px(98, 0.95))])
    assert "首次至今 -2.0%（2026-10-20 收 100，未還原除權息）" in mod.stock_detail(s, "2330.TW")
    assert "至今 -2.0%（未還原）" in mod._index(s)


# ---- unjudged：前幾輪點名過、判斷檔沒有涵蓋的檔，只給事實讓主 agent 決定要不要補判 ----

R24, R25 = "2026-10-24T23:00:00+08:00", "2026-10-25T23:00:00+08:00"


def _logs(tmp_path, rounds=(R24, R25), judge=()):
    d = tmp_path / "logs"
    d.mkdir(exist_ok=True)
    for i, r in enumerate(rounds):
        # 同一份 log 會記兩次 RESULT since=（拿到鎖時與收尾時）
        body = f"x | RESULT since={r}\nx | RESULT since={r}\n"
        body += "".join(f"x | JUDGE {json.dumps(j, ensure_ascii=False)}\n" for j in judge if j["since"] == r)
        (d / f"media_picks_job_{i}.log").write_text(body + "x | JUDGE {broken\n", encoding="utf-8")
    return d


def _unjudged(tmp_path, index_path, media, verdicts=(), judge=(), rounds=(R24, R25), ptt=()):
    _logs(tmp_path, rounds, judge)
    _write(tmp_path / "media-picks-verdicts.jsonl", list(verdicts))
    s = _run(tmp_path, index_path, media)
    if ptt:
        _write(tmp_path / "ptt-picks.jsonl", list(ptt))
        s = mod.summarize(SINCE, journal_dir=tmp_path, transcript_dir=tmp_path / "tr", stock_index=index_path,
                          logs_dir=tmp_path / "logs")
    return s, {c["code"]: c for c in s["unjudged"]["codes"]}


def _prior(code="3037.TW", at="2026-10-25T23:20:00+08:00", **kw):
    return _pick(stock_code=code, name=kw.pop("name", "欣興"), extracted_at=at, date=at[:10], **kw)


def _v(code, since, written, verdict="watch"):
    return {"date": written[:10], "since": since, "code": code, "verdict": verdict, "written_at": written}


def test_unjudged_lists_prior_round_code_without_verdict(tmp_path, index_path):
    # 25 號那輪點名了欣興與台光電，只寫下欣興的判斷（另一檔 claude 逾時）：台光電要出現在證據裡
    media = [_prior(), _prior("2383.TW", name="台光電", stance="bearish"), _pick()]
    s, codes = _unjudged(tmp_path, index_path, media, [_v("3037.TW", R25, "2026-10-25T23:50:00+08:00")])
    assert set(codes) == {"2383.TW"}
    assert "對不到任何一輪 log" not in mod._index(s)
    # 擷取時點早於現存最早一輪 log 的檔：沒有輪可歸，要在索引說明數字為什麼對不上
    early = _prior("1101.TW", at="2026-10-22T14:00:00+08:00", name="台泥")
    s2, codes2 = _unjudged(tmp_path, index_path, media + [early], [_v("3037.TW", R25, "2026-10-25T23:50:00+08:00")])
    assert codes2["1101.TW"]["rounds"] == []
    assert "另有 1 檔的擷取時點對不到任何一輪 log" in mod._index(s2)
    c = codes["2383.TW"]
    assert c["rounds"] == [R25] and c["bear_voices"] == 1 and c["last_verdict"] is None
    assert c["named_this_round"] is False and c["judge_attempts"] == []
    (r24, r25) = s["unjudged"]["rounds"]
    assert (r25["codes_named"], r25["verdict_rows"], r25["unjudged_codes"]) == (2, 1, 1)
    assert r24["codes_named"] == 0


def test_unjudged_old_verdict_does_not_cover_later_naming(tmp_path, index_path):
    # 反向：24 號判過、25 號又被點名卻沒判，舊判斷不能把這次點名蓋掉，要記成 last_verdict
    old = _v("3037.TW", R24, "2026-10-24T23:40:00+08:00", "avoid")
    _, codes = _unjudged(tmp_path, index_path, [_prior()], [old])
    assert codes["3037.TW"]["last_verdict"] == {"date": "2026-10-24", "since": R24, "verdict": "avoid"}
    # 補判：26 號那輪以自己的 since 寫下欣興，25 號的點名就算判過了
    catch_up = _v("3037.TW", SINCE.isoformat(), "2026-10-26T23:50:00+08:00")
    _, codes = _unjudged(tmp_path, index_path, [_prior()], [old, catch_up])
    assert "3037.TW" not in codes


def test_unjudged_window_is_max_days_before_since(tmp_path, index_path):
    # 7 天前以前的點名、以及本輪的點名都不算「前幾輪」
    media = [_prior("1101.TW", at="2026-10-19T22:00:00+08:00", name="台泥"),
             _prior("1102.TW", at="2026-10-19T23:30:00+08:00", name="亞泥"), _pick()]
    s, codes = _unjudged(tmp_path, index_path, media)
    assert set(codes) == {"1102.TW"}
    assert s["unjudged"]["from"] == "2026-10-19T23:00:00+08:00"


def test_unjudged_tolerates_verdict_rows_without_since(tmp_path, index_path):
    # 舊判斷列沒有 since：退回 written_at；連 written_at 都沒有就看 date，不能 KeyError
    rows = [{"code": "3037.TW", "verdict": "watch", "written_at": "2026-10-25T23:50:00+08:00"},
            {"code": "2383.TW", "verdict": "avoid", "date": "2026-10-24"}]
    _, codes = _unjudged(tmp_path, index_path, [_prior(), _prior("2383.TW", name="台光電")], rows)
    assert "3037.TW" not in codes
    assert codes["2383.TW"]["last_verdict"]["verdict"] == "avoid"


def test_unjudged_surfaces_judge_log_errors_and_unwritten_successes(tmp_path, index_path):
    judge = [{"at": "2026-10-25T23:40:00+08:00", "since": R25, "code": "3037.TW", "ok": False, "error": "claude 逾時 300 秒"},
             {"at": "2026-10-25T23:40:00+08:00", "since": R25, "code": "2383.TW", "ok": True, "error": None},
             {"at": "2026-10-25T23:40:00+08:00", "since": R25, "code": "2330.TW", "ok": True, "error": None}]
    media = [_prior(), _prior("2383.TW", name="台光電"), _prior("2330.TW", name="台積電"), _pick()]
    s, codes = _unjudged(tmp_path, index_path, media, [_v("2330.TW", R25, "2026-10-25T23:50:00+08:00")], judge)
    assert codes["3037.TW"]["judge_attempts"] == [{"at": "2026-10-25T23:40:00+08:00", "ok": False,
                                                   "error": "claude 逾時 300 秒"}]
    assert codes["2383.TW"]["judge_attempts"][0]["ok"] is True
    assert "2330.TW" not in codes                     # 判過也寫下的不列
    r25 = s["unjudged"]["rounds"][-1]
    assert (r25["judge_logged"], r25["judge_failed"]) == (3, 1)
    idx = mod._index(s)
    assert "判斷過卻沒寫進判斷檔 2 檔" in idx
    assert "失敗：claude 逾時 300 秒" in idx and "判斷成功、判斷檔沒有對應的列" in idx


def test_unjudged_ignores_judge_attempts_before_the_naming(tmp_path, index_path):
    # 反向：點名之前的判斷紀錄（上週的失敗）不是這次點名的事實
    judge = [{"at": "2026-10-24T23:40:00+08:00", "since": R24, "code": "3037.TW", "ok": False, "error": "x"}]
    _, codes = _unjudged(tmp_path, index_path, [_prior()], judge=judge)
    assert codes["3037.TW"]["judge_attempts"] == []


def test_unjudged_marks_codes_named_again_this_round_and_includes_ptt(tmp_path, index_path):
    ptt = [{"article_id": "M.1", "stock_code": "6274.TWO", "target": "台燿", "resolve": "exact", "stance": "bullish",
            "extracted_at": "2026-10-25T23:30:00+08:00"}]
    _, codes = _unjudged(tmp_path, index_path, [_prior("2330.TW", name="台積電"), _pick()], ptt=ptt)
    assert codes["2330.TW"]["named_this_round"] is True
    assert codes["6274.TWO"]["ptt_articles"] == 1 and codes["6274.TWO"]["name"] == "台燿"


def test_unjudged_index_stays_short_but_full_list_has_every_code(tmp_path, index_path):
    # 前幾輪常有幾百檔沒判斷：索引只放每輪一行，逐檔完整清單在 --unjudged／--json
    media = [_prior(f"{1000 + i}.TW", name=f"股{i}") for i in range(300)] + [_pick()]
    s, codes = _unjudged(tmp_path, index_path, media)
    assert len(codes) == 300
    section = mod._index(s).split("## 前幾輪", 1)[1]
    assert len(section.splitlines()) < 10 and "1000.TW" not in section
    full = mod.unjudged_detail(s)
    assert all(f"{1000 + i}.TW" in full for i in range(300))


def test_cli_unjudged_reads_logs_dir(tmp_path, capsys):
    _write(tmp_path / "media-picks.jsonl", [_prior()])
    logs = _logs(tmp_path)
    argv = ["--since", SINCE.isoformat(), "--unjudged", "--journal-dir", str(tmp_path), "--logs-dir", str(logs)]
    assert mod.main(argv) == 0
    out = capsys.readouterr().out
    assert "欣興 3037.TW" in out and "輪 10-25 23:00：點名 1 檔、判斷檔 0 列" in out


def test_code_detail_carries_prior_evidence_for_unjudged_code_and_marks_holding(tmp_path, index_path):
    # 主 agent 決定補判前幾輪沒判到的檔時，--code（也就是逐檔判斷拿到的原話）不能只回「本輪沒有人點名」
    ptt = [{"article_id": "M.9", "title": "[標的] 欣興 多", "stock_code": "3037.TW", "target": "欣興",
            "resolve": "exact", "stance": "bullish", "reason": "PTT 舊理由",
            "extracted_at": "2026-10-25T23:30:00+08:00"}]
    _logs(tmp_path)
    _write(tmp_path / "media-picks.jsonl", [_prior(quote="舊原話載板"), _prior("2330.TW", name="台積電", quote="舊台積電原話"), _pick()])
    _write(tmp_path / "ptt-picks.jsonl", ptt)
    _write(tmp_path / "media-picks-review.jsonl", [])
    (tmp_path / "held.json").write_text(json.dumps({"codes": [{"code": "3037.TW"}]}), encoding="utf-8")
    s = mod.summarize(SINCE, journal_dir=tmp_path, transcript_dir=tmp_path / "tr", stock_index=index_path,
                      logs_dir=tmp_path / "logs", holdings=tmp_path / "held.json")
    text = mod.stock_detail(s, "3037.TW")
    assert "本輪沒有人點名" in text.splitlines()[1] and "舊原話載板" in text and "PTT 舊理由" in text
    assert text.startswith("（你持有這檔）") and "（持股）" in text
    assert "之前沒被點名過" not in text  # 舊證據沒帶更早紀錄，不能誤寫
    # 反向：已被判斷檔涵蓋的點名不附舊證據，本輪沒點名的檔照舊回「本輪沒有人點名」
    _write(tmp_path / "media-picks-verdicts.jsonl", [_v("3037.TW", R25, "2026-10-25T23:50:00+08:00")])
    s2 = mod.summarize(SINCE, journal_dir=tmp_path, transcript_dir=tmp_path / "tr", stock_index=index_path,
                       logs_dir=tmp_path / "logs")
    assert mod.stock_detail(s2, "3037.TW") == "本輪沒有人點名 3037.TW"
    # 本輪也有點名、前幾輪那次沒被涵蓋的檔：本輪區塊在前，舊證據接在後面
    both = mod.stock_detail(s, "2330.TW")
    assert both.startswith("### 台積電 2330.TW")
    assert both.index("前幾輪點名過、判斷檔沒有涵蓋") < both.index("舊台積電原話")
