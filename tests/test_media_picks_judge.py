"""23:00 媒體點名逐檔判斷：scripts/media_picks_judge.py 的子程序環境、提示詞組裝與回應檢查（不連網、不呼叫真的 claude）。"""
import importlib.util
import json
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("media_picks_judge", ROOT / "scripts" / "media_picks_judge.py")
judge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(judge)

SINCE = datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc)


def _verdict(code, **kw):
    return {"code": code, "verdict": "watch", "thesis": "t", "evidence": ["營收 YoY 50%（2026-09）"], "risks": ["r"],
            "flip": "f", "data_as_of": "2026-10-23"} | kw


class _Summary:
    """假的 media_picks_summary：每檔回一段可辨認的原話。"""

    @staticmethod
    def summarize(since):
        return {"since": since}

    @staticmethod
    def stock_detail(s, code):
        return f"原話-{code}"


def _fake_claude(tmp_path, body: str) -> Path:
    """假 claude：把 stdin 與環境變數存檔，再印 body（body 裡的 {code} 換成提示詞中的代號）。"""
    exe = tmp_path / "claude"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, sys\n"
        "prompt = sys.stdin.read()\n"
        "code = re.search(r'代號：(\\S+)', prompt).group(1)\n"
        f"d = {str(tmp_path)!r}\n"
        "open(os.path.join(d, 'prompt-' + code), 'w').write(prompt)\n"
        "json.dump(dict(os.environ), open(os.path.join(d, 'env-' + code), 'w'))\n"
        f"body = {body!r}\n"
        "if body.startswith('EXIT'):\n"
        "    sys.stderr.write('boom'); sys.exit(3)\n"
        "print(body.replace('{code}', code))\n",
        encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def test_child_env_drops_orca_vars_only():
    env = judge.child_env({"ORCA_PANE_KEY": "x", "ORCA_AGENT_HOOK_URL": "y", "PATH": "/bin", "NOT_ORCA_X": "z",
                           "OPENAI_X": "o", "ORCAX": "w"})
    assert env == {"PATH": "/bin", "NOT_ORCA_X": "z", "OPENAI_X": "o", "ORCAX": "w"}


def test_claude_cmd_disables_hooks_tools_and_mcp():
    cmd = judge.claude_cmd()
    assert cmd[1] == "-p"
    assert json.loads(cmd[cmd.index("--settings") + 1]) == {"disableAllHooks": True}
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd and "--model" not in cmd
    assert judge.claude_cmd("sonnet")[-2:] == ["--model", "sonnet"]


def test_parse_verdict_tolerates_surrounding_text():
    text = "好的，以下是判斷：\n```json\n" + json.dumps(_verdict("2330.TW"), ensure_ascii=False) + "\n```"
    assert judge.parse_verdict(text, "2330.TW")["verdict"] == "watch"


@pytest.mark.parametrize("obj, msg", [
    ({k: v for k, v in _verdict("2330.TW").items() if k != "flip"}, "缺欄位"),
    (_verdict("2330.TW", verdict="buy"), "verdict 不合法"),
    (_verdict("2317.TW"), "code 對不上"),
])
def test_parse_verdict_rejects_bad_objects(obj, msg):
    with pytest.raises(ValueError, match=msg):
        judge.parse_verdict(json.dumps(obj), "2330.TW")


def test_parse_verdict_rejects_non_json():
    with pytest.raises(ValueError):
        judge.parse_verdict("我覺得可以觀察", "2330.TW")


def test_run_keeps_order_builds_prompt_and_strips_orca(tmp_path, monkeypatch):
    exe = _fake_claude(tmp_path, json.dumps(_verdict("{code}")))
    monkeypatch.setenv("MEDIA_PICKS_CLAUDE_BIN", str(exe))
    monkeypatch.setenv("ORCA_PANE_KEY", "pane-1")
    codes = ["3037.TW", "1815.TWO", "2330.TW"]

    out = judge.run(SINCE, codes, dossier_fn=lambda code, t: f"資料包-{code}", summary_mod=_Summary)

    assert [r["code"] for r in out] == codes and all(r["ok"] for r in out)
    prompt = (tmp_path / "prompt-1815.TWO").read_text()
    assert "原話-1815.TWO" in prompt and "資料包-1815.TWO" in prompt and "原話-3037.TW" not in prompt
    assert judge.BRIEF in prompt
    env = json.loads((tmp_path / "env-1815.TWO").read_text())
    assert "ORCA_PANE_KEY" not in env and "PATH" in env


def test_run_reports_failures_per_stock(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_PICKS_CLAUDE_BIN", str(_fake_claude(tmp_path, "EXIT")))
    (bad,) = judge.run(SINCE, ["2330.TW"], dossier_fn=lambda c, t: "", summary_mod=_Summary)
    assert bad["ok"] is False and "rc=3" in bad["error"] and "boom" in bad["error"]

    monkeypatch.setenv("MEDIA_PICKS_CLAUDE_BIN", str(_fake_claude(tmp_path, "沒有 JSON")))
    (bad,) = judge.run(SINCE, ["2330.TW"], dossier_fn=lambda c, t: "", summary_mod=_Summary)
    assert bad["ok"] is False and "沒有 JSON" in bad["raw"]


def test_cli_caps_codes(monkeypatch):
    monkeypatch.setattr(judge, "run", lambda *a, **k: pytest.fail("超過上限不該開始判斷"))
    with pytest.raises(SystemExit) as e:
        judge.main(["--since", "2026-10-26T23:00:00+08:00"] + [f"{1000 + i}.TW" for i in range(judge.MAX_CODES + 1)])
    assert e.value.code == 2


def test_cli_accepts_exactly_max_codes(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(judge, "run", lambda since, codes, **k: seen.append(codes) or [])
    assert judge.main(["--since", "2026-10-26T23:00:00+08:00"] + [f"{1000 + i}.TW" for i in range(judge.MAX_CODES)]) == 0
    assert len(seen[0]) == judge.MAX_CODES and capsys.readouterr().out.strip() == "[]"
