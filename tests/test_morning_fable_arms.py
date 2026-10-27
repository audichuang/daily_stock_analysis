"""scripts/morning_fable_arms.py：Fable 獨立臂（不呼叫真的 claude；subprocess 全部 monkeypatch）。"""
import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("morning_fable_arms", ROOT / "scripts" / "morning_fable_arms.py")
mfa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mfa)

DAY = "2099-03-04"
PACK_TEXT = "PACK-BODY-MARKER 道瓊 +1.0%\n"
GOOD = {"result": "基準率 55%…\n{\"p_close_up\": 0.55, \"p_oc_up\": 0.5, \"p_gap_up\": 0.6, \"reason\": \"基準率→微幅上調\"}",
        "is_error": False, "total_cost_usd": 0.02, "modelUsage": {"claude-fable-x": {}}}
EARLY = dt.datetime(2099, 3, 4, 7, 40, tzinfo=mfa.TAIPEI)
LATE = dt.datetime(2099, 3, 4, 9, 30, tzinfo=mfa.TAIPEI)


class FakeRun:
    """取代 subprocess.run：記錄 argv／kwargs，回預先設定的結果或丟例外。"""

    def __init__(self, stdout=None, returncode=0, exc=None):
        self.stdout = json.dumps(GOOD) if stdout is None else stdout
        self.returncode, self.exc, self.calls = returncode, exc, []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw, sorted(p.name for p in Path(kw["cwd"]).iterdir())))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "boom")


@pytest.fixture
def env(tmp_path, monkeypatch):
    pack = tmp_path / "pack.txt"
    pack.write_text(PACK_TEXT, encoding="utf-8")
    monkeypatch.setenv("MORNING_FABLE_MODEL", "fable-test-model")
    monkeypatch.setattr(mfa.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(mfa, "taipei_now", lambda: EARLY)
    return pack, tmp_path / "arms.jsonl"


def run(env, monkeypatch, fake, *extra):
    pack, out = env
    monkeypatch.setattr(mfa.subprocess, "run", fake)
    rc = mfa.main(["--date", DAY, "--pack", str(pack), "--journal", str(out), *extra])
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()] if out.exists() else []
    return rc, rows


def test_model_unset_skips_with_exit_0_and_no_call(env, monkeypatch, capsys):
    monkeypatch.delenv("MORNING_FABLE_MODEL")
    fake = FakeRun()
    rc, rows = run(env, monkeypatch, fake)
    assert rc == 0 and rows == [] and fake.calls == []
    assert "MORNING_FABLE_MODEL 未設，跳過 Fable 臂" in capsys.readouterr().out


def test_success_row_fields_and_isolation_argv(env, monkeypatch):
    fake = FakeRun()
    rc, rows = run(env, monkeypatch, fake)
    assert rc == 0 and len(rows) == 1
    argv, kw, cwd_listing = fake.calls[0]
    # 隔離旗標一個都不能少，模型名來自 env
    assert argv[argv.index("--model") + 1] == "fable-test-model"
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--system-prompt") + 1] == mfa.SYSTEM_PROMPT
    # prompt 走 stdin，不進 argv；cwd 是空的暫存目錄
    assert PACK_TEXT.strip() in kw["input"] and not any("PACK-BODY-MARKER" in a for a in argv)
    assert cwd_listing == [] and Path(kw["cwd"]) != ROOT
    r = rows[0]
    assert (r["date"], r["model_version"], r["cli_model"]) == (DAY, "fable", "claude-fable-x")
    assert (r["p_close_up"], r["p_oc_up"], r["p_gap_up"]) == (0.55, 0.5, 0.6)
    assert r["error"] is None and r["cost_usd"] == 0.02 and r["reason"] == "基準率→微幅上調"
    assert r["input_snapshot_hash"] == mfa.pack_hash(PACK_TEXT) and r["prompt_hash"] == mfa.prompt_hash()
    assert r["decided_at"] == "2099-03-04T07:40:00+08:00" and r["exclude_from_scoring"] is False


def test_decided_after_0900_is_excluded_from_scoring(env, monkeypatch):
    monkeypatch.setattr(mfa, "taipei_now", lambda: LATE)
    assert run(env, monkeypatch, FakeRun())[1][0]["exclude_from_scoring"] is True


@pytest.mark.parametrize("fake", [
    FakeRun(returncode=1),
    FakeRun(exc=subprocess.TimeoutExpired("claude", 5)),
    FakeRun(stdout="not json at all"),
    FakeRun(stdout=json.dumps({**GOOD, "is_error": True})),   # result 裡有合法 JSON 也不能收
    FakeRun(stdout=json.dumps({**GOOD, "result": "沒有 JSON"})),
    FakeRun(stdout=json.dumps({**GOOD, "result": '{"p_close_up": 1.5, "p_oc_up": 0.5, "p_gap_up": 0.6}'})),
], ids=["nonzero", "timeout", "bad-cli-json", "is_error", "no-json-in-answer", "p-out-of-range"])
def test_failures_write_error_row_and_exit_0(env, monkeypatch, fake):
    rc, rows = run(env, monkeypatch, fake)
    assert rc == 0 and len(rows) == 1 and rows[0]["error"]
    if fake is not None and "1.5" in fake.stdout:
        # 只有不合法的那一欄是 null，合法的保留
        assert rows[0]["p_close_up"] is None and rows[0]["p_oc_up"] == 0.5
    else:
        assert rows[0]["p_close_up"] is rows[0]["p_oc_up"] is rows[0]["p_gap_up"] is None


def test_same_key_is_not_rewritten_nor_called_again(env, monkeypatch, capsys):
    run(env, monkeypatch, FakeRun())
    fake = FakeRun(stdout=json.dumps({**GOOD, "result": '{"p_close_up": 0.1, "p_oc_up": 0.1, "p_gap_up": 0.1}'}))
    rc, rows = run(env, monkeypatch, fake)
    assert rc == 0 and len(rows) == 1 and rows[0]["p_close_up"] == 0.55 and fake.calls == []
    assert "不重寫" in capsys.readouterr().out


def test_other_date_row_does_not_block_this_date(env, monkeypatch):
    _, out = env
    out.write_text(json.dumps({"date": "2099-03-03", "model_version": "fable"}) + "\n", encoding="utf-8")
    assert len(run(env, monkeypatch, FakeRun())[1]) == 2


def test_prompt_never_contains_journal_or_claude_verdict(env, monkeypatch):
    _, out = env
    out.write_text(json.dumps({"date": "2099-03-03", "model_version": "claude", "reason": "CLAUDE-VERDICT-MARKER"}) + "\n",
                   encoding="utf-8")
    fake = FakeRun()
    run(env, monkeypatch, fake)
    argv, kw, _ = fake.calls[0]
    assert "CLAUDE-VERDICT-MARKER" not in kw["input"] + " ".join(argv)
    assert "journal" not in mfa.SYSTEM_PROMPT and "journal" not in mfa.USER_TEMPLATE


def test_dry_run_prints_prompt_and_hashes_without_call_or_write(env, monkeypatch, capsys):
    monkeypatch.delenv("MORNING_FABLE_MODEL")
    fake = FakeRun()
    rc, rows = run(env, monkeypatch, fake, "--dry-run")
    out = capsys.readouterr().out
    assert rc == 0 and rows == [] and fake.calls == []
    assert "PACK-BODY-MARKER" in out and mfa.prompt_hash() in out and mfa.pack_hash(PACK_TEXT) in out


def test_print_hash_outputs_pack_sha256_only(env, monkeypatch, capsys):
    rc, _ = run(env, monkeypatch, FakeRun(), "--print-hash")
    assert rc == 0 and capsys.readouterr().out.strip() == mfa.pack_hash(PACK_TEXT)


def test_target_definitions_are_verbatim_from_skill_step4():
    skill = (ROOT / ".claude" / "skills" / "tw-morning-call" / "SKILL.md").read_text(encoding="utf-8")
    for line in ("- `p_close_up`：收盤高於前一日收盤（**主目標**）",
                 "- `p_oc_up`：收盤高於當日官方開盤（**主目標**）",
                 "- `p_gap_up`：09:05 加權指數高於前一日收盤（次要）"):
        assert line in skill and line in mfa.USER_TEMPLATE


def test_parse_result_takes_last_object_and_rejects_bad_p():
    ps, reason, err = mfa.parse_result('先試 {"p_close_up": 0.9} 再 {"p_close_up": 0.4, "p_oc_up": 0.5, "p_gap_up": 0.6}')
    assert (ps["p_close_up"], err) == (0.4, None)
    for bad in ("NaN", "true", '"0.6"', "-0.1", "62"):
        ps, _, err = mfa.parse_result('{"p_close_up": 0.4, "p_oc_up": 0.5, "p_gap_up": %s}' % bad)
        assert ps["p_gap_up"] is None and ps["p_oc_up"] == 0.5 and "p_gap_up" in err
    assert mfa.parse_result("沒有物件")[2]


def test_find_pack_prefers_earliest_of_the_day(tmp_path):
    for n in ("2099-03-04.081500.txt", "2099-03-04.073100.txt", "2099-03-05.txt"):
        (tmp_path / n).write_text("x")
    assert mfa.find_pack(DAY, tmp_path).name == "2099-03-04.073100.txt"
    (tmp_path / "2099-03-04.txt").write_text("x")
    assert mfa.find_pack(DAY, tmp_path).name == "2099-03-04.txt"
    assert mfa.find_pack("2099-03-09", tmp_path) is None


def test_append_row_refuses_same_key_directly(tmp_path):
    out = tmp_path / "a.jsonl"
    assert mfa.append_row(out, {"date": DAY, "model_version": "fable", "n": 1}) is True
    assert mfa.append_row(out, {"date": DAY, "model_version": "fable", "n": 2}) is False
    assert len(out.read_text().splitlines()) == 1


# ---------- 第 1 輪審查修正 ----------

def make_pack(marker="JOURNAL-MARKER"):
    return (f"預備資料 OK\n\n===== 大局（總經）=====\nMACRO-KEEP\n"
            f"\n===== 近期判讀校正（盤前預估 vs 實際）=====\nCALIB {marker}\n多臂（描述性）：fable {marker}\n"
            f"\n===== 昨晚国际盘 =====\nINTL-KEEP\n"
            f"\n===== 期交所籌碼（前一交易日）=====\nTAIFEX-KEEP\n"
            f"\n===== 待触发计划（已留档、未到期）=====\nPLAN {marker}\n\n"
            f"===== 最近一輪媒體點名（2099-03-03，僅供參考，不是買進訊號）=====\nMEDIA {marker}\n"
            f"\n===== 今日候选 =====\nCAND-KEEP\n下一步：…\n")


def test_filter_pack_drops_journal_sections_keeps_data_sections():
    out = mfa.filter_pack(make_pack())
    assert "JOURNAL-MARKER" not in out
    for keep in ("預備資料 OK", "MACRO-KEEP", "INTL-KEEP", "TAIFEX-KEEP", "CAND-KEEP"):
        assert keep in out


def test_filter_pack_drops_headerless_media_lines_inside_plan_section():
    pack = "===== 昨晚国际盘 =====\nINTL\n===== 待触发计划（x）=====\nP\n\n沒有媒體點名判斷 MARK\n===== 今日候选 =====\nC\n"
    out = mfa.filter_pack(pack)
    assert "MARK" not in out and "INTL" in out and "C\n" in out


def test_prompt_and_hash_use_filtered_pack(tmp_path, monkeypatch, capsys):
    pack = tmp_path / "p.txt"
    pack.write_text(make_pack(), encoding="utf-8")
    out = tmp_path / "arms.jsonl"
    monkeypatch.setenv("MORNING_FABLE_MODEL", "m")
    monkeypatch.setattr(mfa.shutil, "which", lambda n: "/usr/bin/claude")
    fake = FakeRun()
    monkeypatch.setattr(mfa.subprocess, "run", fake)
    assert mfa.main(["--date", DAY, "--pack", str(pack), "--journal", str(out)]) == 0
    sent = fake.calls[0][1]["input"]
    assert "JOURNAL-MARKER" not in sent and "MACRO-KEEP" in sent and "CAND-KEEP" in sent
    row = json.loads(out.read_text())
    filtered_hash = mfa.pack_hash(mfa.filter_pack(make_pack()))
    assert row["input_snapshot_hash"] == filtered_hash != mfa.pack_hash(make_pack())
    capsys.readouterr()
    assert mfa.main(["--date", DAY, "--pack", str(pack), "--print-hash"]) == 0
    assert capsys.readouterr().out.strip() == filtered_hash


def test_child_env_strips_orca_and_claude_code_vars():
    env = mfa.child_env({"ORCA_X": "1", "CLAUDE_CODE_OAUTH_TOKEN": "t", "CLAUDE_CODE_ENTRYPOINT": "cli",
                         "CLAUDECODE": "1", "PATH": "/bin", "USER": "u", "CLAUDE_OTHER": "keep"})
    assert env == {"PATH": "/bin", "USER": "u", "CLAUDE_OTHER": "keep"}


def test_subprocess_gets_clean_env_and_hooks_disabled(env, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCA_TERMINAL", "x")
    fake = FakeRun()
    run(env, monkeypatch, fake)
    argv, kw, _ = fake.calls[0]
    assert not any(k.startswith(("CLAUDE_CODE_", "ORCA_")) or k == "CLAUDECODE" for k in kw["env"])
    assert argv[argv.index("--settings") + 1] == '{"disableAllHooks":true}'


def test_template_example_is_not_parseable_as_an_answer():
    example = next(ln for ln in mfa.USER_TEMPLATE.splitlines() if ln.startswith('{{"p_close_up"'))
    ps, _, err = mfa.parse_result(example.replace("{{", "{").replace("}}", "}"))
    assert err and all(v is None for v in ps.values())


def test_text_after_last_json_object_is_an_error():
    valid = '{"p_close_up": 0.6, "p_oc_up": 0.5, "p_gap_up": 0.5}'
    ps, _, err = mfa.parse_result(f'格式 {valid}\n最終 {{"p_close_up": 0.6, "p_oc_up": 0.5, "p_gap_up": 0.5,}}')
    assert err and all(v is None for v in ps.values())
    ps, _, err = mfa.parse_result(f"{valid}\n補充說明")
    assert err and all(v is None for v in ps.values())
    ps, _, err = mfa.parse_result(f"分析…\n{valid}\n  \n")
    assert err is None and ps["p_close_up"] == 0.6


def test_print_hash_without_pack_prints_nothing_on_stdout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mfa, "PACK_DIR", tmp_path)
    assert mfa.main(["--date", DAY, "--print-hash"]) == 1
    cap = capsys.readouterr()
    assert cap.out == "" and "找不到" in cap.err


def test_find_pack_never_picks_partial_or_malformed_names(tmp_path):
    for n in ("2099-03-04.123.partial", "2099-03-04.0001.txt", "2099-03-04.abc.txt", "2099-03-04.090000.txt"):
        (tmp_path / n).write_text("x")
    assert mfa.find_pack(DAY, tmp_path).name == "2099-03-04.090000.txt"
    for n in ("2099-03-04.090000.txt",):
        (tmp_path / n).unlink()
    assert mfa.find_pack(DAY, tmp_path) is None


# ---------- 綜合臂（--synth）----------

FROZEN_INDEP_PROMPT_HASH = "ec661c2fe319706a47b6d83784d8a3453ea2a9069df40398c09371656067d6ec"  # develop 49263158 的值
SYNTH_GOOD = {**GOOD, "result": "綜合…\n{\"p_close_up\": 0.58, \"p_oc_up\": 0.52, \"p_gap_up\": 0.61, \"reason\": \"兩成員接近\"}"}
CLAUDE_P = {"p_close_up": 0.6, "p_oc_up": 0.45, "p_gap_up": 0.7}
FABLE_P = {"p_close_up": 0.55, "p_oc_up": 0.5, "p_gap_up": 0.6}


def claude_row(**kw):
    return {"date": DAY, "model_version": "claude", **CLAUDE_P, "exclude_from_scoring": False,
            "input_snapshot_hash": mfa.pack_hash(PACK_TEXT), "reason": "CLAUDE-REASON-MARKER",
            "action": "CLAUDE-ACTION-MARKER", "regime": "CLAUDE-REGIME-MARKER", **kw}


def fable_row(**kw):
    return {"date": DAY, "model_version": "fable", **FABLE_P, "error": None,
            "input_snapshot_hash": mfa.pack_hash(PACK_TEXT), "reason": "FABLE-REASON-MARKER", **kw}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def run_synth(env, monkeypatch, fake, claude=None, fable=None, extra_arms=()):
    pack, out = env
    calls = out.parent / "calls.jsonl"
    write_jsonl(calls, [claude] if claude is not None else [])
    write_jsonl(out, [fable] if fable is not None else [])
    if extra_arms:
        write_jsonl(out, [*([fable] if fable is not None else []), *extra_arms])
    monkeypatch.setattr(mfa.subprocess, "run", fake)
    rc = mfa.main(["--date", DAY, "--pack", str(pack), "--journal", str(out), "--calls", str(calls), "--synth"])
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    return rc, rows


def test_synth_prompt_has_only_numbers_never_reason_action_or_regime(env, monkeypatch):
    fake = FakeRun(stdout=json.dumps(SYNTH_GOOD))
    rc, rows = run_synth(env, monkeypatch, fake, claude_row(), fable_row())
    sent = fake.calls[0][1]["input"]
    assert not any(m in " ".join(fake.calls[0][0]) for m in ("MARKER", "0.58"))
    for marker in ("CLAUDE-REASON-MARKER", "CLAUDE-ACTION-MARKER", "CLAUDE-REGIME-MARKER", "FABLE-REASON-MARKER"):
        assert marker not in sent
        assert "成員 A" in sent and "成員 B" in sent and "claude" not in sent.lower() and "fable" not in sent.lower()
    assert PACK_TEXT.strip() in sent
    # A＝claude、B＝fable：A 欄在前
    assert "| `p_close_up` | 0.6 | 0.55 |" in sent and "| `p_oc_up` | 0.45 | 0.5 |" in sent


def test_synth_row_fields_member_p_and_hashes(env, monkeypatch):
    rc, rows = run_synth(env, monkeypatch, FakeRun(stdout=json.dumps(SYNTH_GOOD)), claude_row(), fable_row())
    assert rc == 0 and len(rows) == 2
    r = rows[1]
    assert (r["date"], r["model_version"], r["error"]) == (DAY, "fable_synth", None)
    assert (r["p_close_up"], r["p_oc_up"], r["p_gap_up"]) == (0.58, 0.52, 0.61)
    assert r["member_p"] == {"claude": CLAUDE_P, "fable": FABLE_P}
    assert r["input_snapshot_hash"] == mfa.pack_hash(PACK_TEXT)    # 與獨立臂同一份
    assert r["prompt_hash"] == mfa.prompt_hash(mfa.SYNTH_TEMPLATE) != mfa.prompt_hash()
    assert r["exclude_from_scoring"] is False


def test_synth_decided_after_0900_is_excluded(env, monkeypatch):
    monkeypatch.setattr(mfa, "taipei_now", lambda: LATE)
    rows = run_synth(env, monkeypatch, FakeRun(stdout=json.dumps(SYNTH_GOOD)), claude_row(), fable_row())[1]
    assert rows[1]["exclude_from_scoring"] is True


@pytest.mark.parametrize("claude,fable", [
    (None, fable_row()),
    (claude_row(p_oc_up=None), fable_row()),
    (claude_row(p_gap_up=1.2), fable_row()),
    (claude_row(exclude_from_scoring=True), fable_row()),
    (claude_row(exclude_from_scoring=None), fable_row()),
    (claude_row(input_snapshot_hash="OTHER"), fable_row()),
    (claude_row(input_snapshot_hash=None), fable_row()),
    (claude_row(), None),
    (claude_row(), fable_row(error="逾時")),
    (claude_row(), fable_row(p_close_up=None)),
    (claude_row(), fable_row(p_gap_up=True)),
], ids=["no-claude", "claude-p-null", "claude-p-range", "claude-excluded", "claude-excl-missing", "hash-mismatch",
        "hash-missing", "no-fable", "fable-error", "fable-p-null", "fable-p-bool"])
def test_synth_missing_precondition_means_no_call_no_row_exit_0(env, monkeypatch, capsys, claude, fable):
    fake = FakeRun(stdout=json.dumps(SYNTH_GOOD))
    rc, rows = run_synth(env, monkeypatch, fake, claude, fable)
    assert rc == 0 and fake.calls == []
    assert all(r["model_version"] != "fable_synth" for r in rows)
    assert "前置條件不成立" in capsys.readouterr().out


def test_synth_ignores_other_dates_and_other_models_rows(env, monkeypatch):
    other = [{**fable_row(), "date": "2099-03-03"}, {**fable_row(), "model_version": "equal_weight"}]
    fake = FakeRun(stdout=json.dumps(SYNTH_GOOD))
    rc, rows = run_synth(env, monkeypatch, fake, claude_row(model_version="claude"), None, extra_arms=other)
    assert fake.calls == [] and all(r["model_version"] != "fable_synth" for r in rows)


def test_synth_same_key_is_not_rewritten_nor_called_again(env, monkeypatch, capsys):
    pack, out = env
    run_synth(env, monkeypatch, FakeRun(stdout=json.dumps(SYNTH_GOOD)), claude_row(), fable_row())
    capsys.readouterr()
    fake = FakeRun(stdout=json.dumps({**GOOD, "result": '{"p_close_up": 0.1, "p_oc_up": 0.1, "p_gap_up": 0.1}'}))
    monkeypatch.setattr(mfa.subprocess, "run", fake)
    rc = mfa.main(["--date", DAY, "--pack", str(pack), "--journal", str(out), "--calls", str(out.parent / "calls.jsonl"),
                   "--synth"])
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert rc == 0 and fake.calls == [] and len(rows) == 2 and rows[1]["p_close_up"] == 0.58
    assert "不重寫" in capsys.readouterr().out


def test_synth_failure_still_writes_error_row_with_member_p(env, monkeypatch):
    rc, rows = run_synth(env, monkeypatch, FakeRun(returncode=1), claude_row(), fable_row())
    assert rc == 0 and rows[1]["model_version"] == "fable_synth" and rows[1]["error"]
    assert rows[1]["p_close_up"] is None and rows[1]["member_p"]["claude"] == CLAUDE_P


def test_synth_does_not_block_independent_arm_key_and_vice_versa(tmp_path):
    out = tmp_path / "a.jsonl"
    assert mfa.append_row(out, {"date": DAY, "model_version": "fable"}) is True
    assert mfa.append_row(out, {"date": DAY, "model_version": "fable_synth"}) is True
    assert mfa.append_row(out, {"date": DAY, "model_version": "fable_synth"}) is False


def test_synth_template_shares_target_definitions_and_independent_prompt_is_frozen():
    for line in ("- `p_close_up`：收盤高於前一日收盤（**主目標**）",
                 "- `p_oc_up`：收盤高於當日官方開盤（**主目標**）",
                 "- `p_gap_up`：09:05 加權指數高於前一日收盤（次要）"):
        assert line in mfa.SYNTH_TEMPLATE and line in mfa.USER_TEMPLATE
    # 獨立臂 prompt_hash 已登記實驗，改了就作廢：釘死目前的值
    assert mfa.prompt_hash() == FROZEN_INDEP_PROMPT_HASH


def test_synth_dry_run_prints_prompt_without_call_or_write(env, monkeypatch, capsys):
    pack, out = env
    write_jsonl(out.parent / "calls.jsonl", [claude_row()])
    write_jsonl(out, [fable_row()])
    fake = FakeRun()
    monkeypatch.setattr(mfa.subprocess, "run", fake)
    before = out.read_text(encoding="utf-8")
    rc = mfa.main(["--date", DAY, "--pack", str(pack), "--journal", str(out), "--calls", str(out.parent / "calls.jsonl"),
                   "--synth", "--dry-run"])
    text = capsys.readouterr().out
    assert rc == 0 and fake.calls == [] and out.read_text(encoding="utf-8") == before
    assert "成員 A" in text and mfa.prompt_hash(mfa.SYNTH_TEMPLATE) in text


def test_synth_accepts_boundary_probabilities_zero_and_one(env, monkeypatch):
    fake = FakeRun(stdout=json.dumps(SYNTH_GOOD))
    rc, rows = run_synth(env, monkeypatch, fake, claude_row(p_close_up=1.0, p_gap_up=0), fable_row(p_oc_up=0.0, p_gap_up=1))
    assert len(fake.calls) == 1 and rows[1]["model_version"] == "fable_synth"


@pytest.mark.parametrize("fable", [fable_row(input_snapshot_hash=None), fable_row(input_snapshot_hash="OTHER")],
                         ids=["fable-hash-missing", "fable-hash-mismatch"])
def test_synth_requires_fable_row_hash_to_match_the_pack(env, monkeypatch, capsys, fable):
    fake = FakeRun(stdout=json.dumps(SYNTH_GOOD))
    rc, rows = run_synth(env, monkeypatch, fake, claude_row(), fable)
    assert rc == 0 and fake.calls == [] and all(r["model_version"] != "fable_synth" for r in rows)
    assert "前置條件不成立" in capsys.readouterr().out
