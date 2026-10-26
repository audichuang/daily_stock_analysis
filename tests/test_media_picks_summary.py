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


def _backlog(tmp_path, media, ptt=(), verdicts=(), review=(), logs=(), max_days=7):
    for name, rows in (("media-picks", media), ("ptt-picks", ptt),
                       ("media-picks-verdicts", verdicts), ("media-picks-review", review)):
        _write(tmp_path / f"{name}.jsonl", rows)
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "media_picks_job_test.log").write_text("\n".join(logs), encoding="utf-8")
    return mod.summarize(CUR, journal_dir=tmp_path, logs_dir=log_dir, max_days=max_days)


def test_unjudged_partial_round_includes_media_and_ptt_without_changing_judge_since(tmp_path):
    at = "2026-10-26T00:20:00+08:00"  # 25 號開始、跨午夜擷取
    verdicts = [{"code": "2330.TW", "verdict": "watch", "since": _t(25).isoformat()}]
    err = {"event": "media_picks_judge_error", "since": _t(25).isoformat(),
           "code": "00631L.TW", "ok": False, "error": "claude 逾時"}
    s = _backlog(tmp_path,
                 [_pick(extracted_at=at), _pick(stock_code="00631L.TW", extracted_at=at, reason="ETF 原話")],
                 ptt=[{"stock_code": "6811.TWO", "extracted_at": at, "article_id": "M.1", "reason": "PTT 原話"}],
                 verdicts=verdicts, logs=["RESULT since=" + _t(25).isoformat(), json.dumps(err)])
    pending = {r["code"]: r for r in s["unjudged"]}
    assert set(pending) == {"00631L.TW", "6811.TWO"}
    assert pending["00631L.TW"]["mentions"] == [
        {"source": "media", "round_since": _t(25).isoformat(), "extracted_at": at, "id": "v1"}]
    assert pending["00631L.TW"]["judge_error_logged"] is True
    assert pending["00631L.TW"]["judge_errors"][0]["error"] == "claude 逾時"
    assert pending["6811.TWO"]["judge_error_logged"] is False
    assert "ETF 原話" in mod.stock_detail(s, "00631L.TW")
    assert "PTT 原話" in mod.stock_detail(s, "6811.TWO")
    assert "先前點名但沒有 verdict" in mod._index(s) and "6811.TWO" in mod._index(s)
    assert s["stocks"] == [] and s["ptt"] == []  # 舊證據不能混入本輪統計
    assert mod.judge_since(CUR, verdicts, [_t(25), CUR]) == CUR


def test_unjudged_works_without_round_logs_or_any_verdict_and_does_not_infer_errors(tmp_path):
    at = _t(25).isoformat()
    s = _backlog(tmp_path, [_pick(extracted_at=at, reason="claude timeout ok:false watch")],
                 logs=['claude timeout 2330.TW', '{broken',
                       json.dumps({"code": "2330.TW", "since": at, "error": "自由文字以外仍缺事件欄"})])
    (row,) = s["unjudged"]
    assert row["mentions"][0]["round_since"] is None
    assert row["judge_error_logged"] is False and row["judge_errors"] == []
    assert "未找到結構化錯誤紀錄" in mod._index(s)
    assert "claude timeout ok:false watch" in mod.stock_detail(s, "2330.TW")
    assert not {"verdict", "rejudge", "retry", "recommendation"} & row.keys()
    assert mod.judge_since(CUR, [], [_t(25)]) == CUR


def test_unjudged_filters_window_and_only_real_verdict_rows_clear_codes(tmp_path):
    rows = [_pick(stock_code=c, extracted_at=at) for c, at in [
        ("2330.TW", _t(19).isoformat()), ("6811.TWO", _t(18).isoformat()),
        ("00631L.TW", CUR.isoformat()), ("2887A.TW", _t(25).isoformat()),
        ("2317.TW", _t(25).isoformat()), ("2454.TW", "invalid")]]
    s = _backlog(tmp_path, rows, verdicts=[
        {"code": "2330.TW", "ok": False, "error": "timeout"},
        {"code": "2887A.TW", "verdict": "avoid"},
        {"code": "2317.TW", "verdict": "research", "since": _t(1).isoformat()}])
    assert [r["code"] for r in s["unjudged"]] == ["2330.TW"]
    s = _backlog(tmp_path, rows, max_days=30)
    assert "6811.TWO" in {r["code"] for r in s["unjudged"]}


def test_unjudged_applies_reviews_keeps_all_mentions_and_later_verdict_clears(tmp_path):
    old = _pick(**UNRES, extracted_at=_t(25).isoformat(), reason="更正後的證據")
    discarded = _pick(stock_code="2887A.TW", video_id="v2", extracted_at=_t(25).isoformat())
    reviews = [_verdict(old, "correct", "1326.TW"), _verdict(discarded, "not_stock")]
    media = [old, _pick(stock_code="1326.TW", video_id="v3", extracted_at=_t(24).isoformat()), discarded]
    s = _backlog(tmp_path, media, review=reviews)
    (row,) = s["unjudged"]
    assert row["code"] == "1326.TW" and len(row["mentions"]) == 2
    assert "更正後的證據" in mod.stock_detail(s, "1326.TW")
    assert _backlog(tmp_path, media, review=reviews,
                    verdicts=[{"code": "1326.TW", "verdict": "watch", "since": CUR.isoformat()}])["unjudged"] == []


def test_cli_exposes_unjudged_in_json_index_and_code_using_logs_dir(tmp_path, capsys):
    _backlog(tmp_path, [_pick(extracted_at=_t(25).isoformat(), reason="缺判原話")],
             logs=["RESULT since=" + _t(25).isoformat()])
    argv = ["--since", CUR.isoformat(), "--journal-dir", str(tmp_path), "--logs-dir", str(tmp_path / "logs")]
    assert mod.main(argv + ["--json"]) == 0
    row = json.loads(capsys.readouterr().out)["unjudged"][0]
    assert row["code"] == "2330.TW" and row["mentions"][0]["round_since"] == _t(25).isoformat()
    assert mod.main(argv + ["--index"]) == 0
    assert "最早 round since=" + _t(25).isoformat() in capsys.readouterr().out
    assert mod.main(argv + ["--code", "2330.TW"]) == 0
    assert "缺判原話" in capsys.readouterr().out


def test_unjudged_does_not_cap_candidates_or_mix_current_and_prior_evidence(tmp_path):
    media = [_pick(stock_code=f"{1000 + i}.TW", extracted_at=_t(25).isoformat()) for i in range(10)]
    media += [_pick(extracted_at=_t(25).isoformat(), reason="先前原話"), _pick(reason="本輪原話")]
    s = _backlog(tmp_path, media)
    assert len(s["unjudged"]) == 11  # MAX_CODES 限制的是 agent 選出的判讀，不是證據清單
    detail = mod.stock_detail(s, "2330.TW")
    assert "先前原話" in detail and "本輪原話" in detail
    assert [r["code"] for r in s["stocks"]] == ["2330.TW"]
    assert mod.stock_detail(s, "9999.TW") == "本輪沒有人點名 9999.TW"


def test_unjudged_marks_ptt_only_holding_and_filters_structured_error_window(tmp_path):
    err = {"event": "media_picks_judge_error", "code": "6811.TWO", "ok": False, "error": "timeout"}
    s = _backlog(tmp_path, [], ptt=[{"stock_code": "6811.TWO", "extracted_at": _t(25).isoformat(),
                                    "article_id": "M.1", "reason": "持股的舊文章"}],
                 logs=[json.dumps(err | {"since": at, "ok": ok}) for at, ok in [
                     (_t(18).isoformat(), False), (CUR.isoformat(), False), ("invalid", False),
                     (_t(25).isoformat(), True)]])
    assert s["unjudged"][0]["judge_errors"] == []
    holdings = tmp_path / "holdings.json"
    holdings.write_text(json.dumps({"codes": [{"code": "6811.TWO"}]}), encoding="utf-8")
    s = mod.summarize(CUR, journal_dir=tmp_path, logs_dir=tmp_path / "logs", holdings=holdings)
    assert "（你持有這檔）" in mod.stock_detail(s, "6811.TWO")
    assert s["holdings"]["mentioned"] == []


def test_unjudged_index_compacts_repeated_mentions_but_detail_retains_every_source(tmp_path):
    media = [_pick(video_id=f"v{i}", extracted_at=_t(25).isoformat(), reason=f"理由{i}") for i in range(50)]
    s = _backlog(tmp_path, media, logs=["RESULT since=" + _t(25).isoformat()])
    line, = [line for line in mod._index(s).splitlines() if "2330.TW" in line]
    assert "點名 50 筆" in line and line.count("extracted_at=") == 1 and len(line) < 200
    detail = mod.stock_detail(s, "2330.TW")
    assert all(f"理由{i}" in detail and f"media v{i}：" in detail for i in range(50))
    assert len(s["unjudged"][0]["mentions"]) == 50
