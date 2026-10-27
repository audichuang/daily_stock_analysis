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
    assert r["input_snapshot_hash"] == mfa.pack_hash(PACK_TEXT.encode()) and r["prompt_hash"] == mfa.prompt_hash()
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
    assert "PACK-BODY-MARKER" in out and mfa.prompt_hash() in out and mfa.pack_hash(PACK_TEXT.encode()) in out


def test_print_hash_outputs_pack_sha256_only(env, monkeypatch, capsys):
    rc, _ = run(env, monkeypatch, FakeRun(), "--print-hash")
    assert rc == 0 and capsys.readouterr().out.strip() == mfa.pack_hash(PACK_TEXT.encode())


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
    for n in ("2099-03-04.0815.txt", "2099-03-04.0731.txt", "2099-03-05.txt"):
        (tmp_path / n).write_text("x")
    assert mfa.find_pack(DAY, tmp_path).name == "2099-03-04.0731.txt"
    (tmp_path / "2099-03-04.txt").write_text("x")
    assert mfa.find_pack(DAY, tmp_path).name == "2099-03-04.txt"
    assert mfa.find_pack("2099-03-09", tmp_path) is None


def test_append_row_refuses_same_key_directly(tmp_path):
    out = tmp_path / "a.jsonl"
    assert mfa.append_row(out, {"date": DAY, "model_version": "fable", "n": 1}) is True
    assert mfa.append_row(out, {"date": DAY, "model_version": "fable", "n": 2}) is False
    assert len(out.read_text().splitlines()) == 1
