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


@pytest.fixture(autouse=True)
def _no_real_records(monkeypatch):
    """預設不跑 uv／連 DB 取講者紀錄；要測的測試自己傳 records_fn。"""
    monkeypatch.setattr(judge, "load_records", lambda timeout=0: {})


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


def test_worst_case_per_stock_fits_under_bash_ceiling(monkeypatch):
    # 平行跑時總時長 ≈ 單檔最壞（資料包＋判斷串行）；至少留 120 秒給摘要、uv 與 claude 冷啟動
    assert judge.DOSSIER_TIMEOUT + judge.JUDGE_TIMEOUT <= judge.BASH_CEILING - 120
    seen = {}
    monkeypatch.setattr(judge, "judge_one", lambda code, m, d, model, timeout: seen.setdefault("t", timeout) and {})
    judge.run(SINCE, ["2330.TW"], dossier_fn=lambda c, t: seen.setdefault("d", t) and "", summary_mod=_Summary)
    assert seen == {"d": judge.DOSSIER_TIMEOUT, "t": judge.JUDGE_TIMEOUT}


def test_cli_passes_judge_timeout_by_default_and_timeouts_are_nonzero(monkeypatch):
    seen = {}
    monkeypatch.setattr(judge, "run", lambda since, codes, **k: seen.update(k) or [])
    assert judge.main(["--since", "2026-10-26T23:00:00+08:00", "2330.TW"]) == 0
    assert seen["timeout"] == judge.JUDGE_TIMEOUT
    assert judge.JUDGE_TIMEOUT >= 60 and judge.DOSSIER_TIMEOUT >= 30   # 設成 0 會讓每檔立刻逾時


class _SummaryWithVoices(_Summary):
    @staticmethod
    def summarize(since):
        return {"since": since, "stocks": [{"code": "2330.TW", "voices": [
            {"speaker": "甲", "show": "A"}, {"speaker": "", "show": "某節目"}]}]}


_REC = {"甲": {"bull": {"n_calls": 30, "n": 25, "dates": 9, "hit_rate": 0.6, "mean_excess": 0.0123, "enough": True},
               "bear": {"n_calls": 3, "n": 2, "dates": 2, "hit_rate": 1.0, "mean_excess": -0.05, "enough": False}},
        "乙": {"bull": {"n_calls": 40, "n": 40, "dates": 12, "hit_rate": 0.9, "mean_excess": 0.2, "enough": True}}}


def test_records_section_formats_enough_and_small_samples():
    text = judge.records_section(_REC, ["甲", "乙"])
    assert "三、講者過去紀錄" in text
    assert "命中率 60%" in text and "+1.23%" in text                      # n=25 夠
    assert "已到期 2 筆、進場日 2 天（共 3 次點名），樣本不足" in text            # n=2 不夠
    assert "看空／避開，無紀錄" in text                                      # 乙沒有看空紀錄
    # 邊界：n=19 不夠、n=20 夠
    edge = lambda n, d=9: judge.records_section({"甲": {"bull": {"n_calls": n, "n": n, "dates": d, "hit_rate": 0.5, "mean_excess": 0.01}}}, ["甲"])  # noqa: E731
    assert "樣本不足" in edge(19).split("\n")[3] and "樣本不足" not in edge(20)
    # 進場日邊界：n 夠但進場日只有 4 天不夠、5 天夠；沒有 dates 欄一律不夠
    assert "樣本不足" in edge(20, 4) and "樣本不足" not in edge(20, 5)
    no_dates = judge.records_section({"甲": {"bull": {"n_calls": 30, "n": 30, "hit_rate": 0.5, "mean_excess": 0.01}}}, ["甲"])
    assert "樣本不足" in no_dates


def test_records_section_failure_text_and_unknown_speaker():
    assert "（講者紀錄取不到：boom）" in judge.records_section(RuntimeError("boom"), ["甲"])
    assert "看多，無紀錄；看空／避開，無紀錄" in judge.records_section({}, ["新人"])


def test_run_appends_records_once_and_survives_load_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_PICKS_CLAUDE_BIN", str(_fake_claude(tmp_path, json.dumps(_verdict("{code}")))))
    calls = []
    out = judge.run(SINCE, ["2330.TW", "2317.TW"], dossier_fn=lambda c, t: "", summary_mod=_SummaryWithVoices,
                    records_fn=lambda: calls.append(1) or _REC)
    assert all(r["ok"] for r in out) and len(calls) == 1                  # 兩檔只載一次
    prompt = (tmp_path / "prompt-2330.TW").read_text()
    assert "三、講者過去紀錄" in prompt and "- 甲：" in prompt and "- [某節目]：" in prompt and "乙" not in prompt

    def boom():
        raise RuntimeError("db down")
    out = judge.run(SINCE, ["2330.TW"], dossier_fn=lambda c, t: "", summary_mod=_SummaryWithVoices, records_fn=boom)
    assert out[0]["ok"] is True
    assert "（講者紀錄取不到：db down）" in (tmp_path / "prompt-2330.TW").read_text()


def test_brief_mentions_records_and_small_sample_rule():
    assert "三、講者過去紀錄" in judge.BRIEF and "n<20" in judge.BRIEF
    assert judge.RECORDS_TIMEOUT <= judge.DOSSIER_TIMEOUT


def test_cli_log_appends_one_judge_line_per_code_that_summary_reads(tmp_path, monkeypatch):
    # --log：每檔一行判斷紀錄寫進本輪 log，下一輪摘要讀得回來（失敗附原因、成功不帶 error）
    log = tmp_path / "media_picks_job_1.log"
    log.write_text("x | RESULT since=2026-10-26T23:00:00+08:00\n", encoding="utf-8")
    out = [{"code": "2330.TW", "ok": True, "result": {}}, {"code": "3037.TW", "ok": False, "error": "claude 逾時 300 秒"}]
    monkeypatch.setattr(judge, "run", lambda since, codes, **k: out)
    assert judge.main(["--since", "2026-10-26T23:00:00+08:00", "--log", str(log), "2330.TW", "3037.TW"]) == 0
    rows = judge._load_summary().judge_log(tmp_path)
    assert [(r["code"], r["ok"], r["error"]) for r in rows] == [("2330.TW", True, None),
                                                                ("3037.TW", False, "claude 逾時 300 秒")]
    assert all(r["since"] == "2026-10-26T23:00:00+08:00" and r["at"] for r in rows)
    assert log.read_text(encoding="utf-8").startswith("x | RESULT since=")   # 只追加，不改原本的 log


def test_cli_without_log_writes_nothing_and_bad_log_path_does_not_fail(tmp_path, monkeypatch, capsys):
    # 反向：沒給 --log 不寫任何檔；log 路徑寫不進去也照樣印出判斷結果
    monkeypatch.setattr(judge, "run", lambda since, codes, **k: [{"code": "2330.TW", "ok": True, "result": {}}])
    monkeypatch.chdir(tmp_path)
    assert judge.main(["--since", "2026-10-26T23:00:00+08:00", "2330.TW"]) == 0
    assert list(tmp_path.iterdir()) == []
    capsys.readouterr()
    assert judge.main(["--since", "2026-10-26T23:00:00+08:00", "--log", str(tmp_path / "no" / "x.log"), "2330.TW"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)[0]["code"] == "2330.TW" and "判斷紀錄寫不進" in captured.err


def test_run_passes_prior_unjudged_evidence_and_speaker_records_to_agent(tmp_path, monkeypatch):
    # 補判前幾輪的檔：提示詞要有舊原話，舊講者的過去紀錄也要附上
    from types import SimpleNamespace

    summary = judge._load_summary()
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "media_picks_job_1.log").write_text("x | RESULT since=2026-10-25T23:00:00+08:00\n", encoding="utf-8")
    media = {"stock_code": "00631L.TW", "name": "元大台灣50正2", "extracted_at": "2026-10-25T23:30:00+08:00",
             "video_id": "v", "speaker": "甲", "show": "節目", "reason": "補判原話", "stance": "bullish"}
    (tmp_path / "media-picks.jsonl").write_text(json.dumps(media) + "\n", encoding="utf-8")
    mod = SimpleNamespace(summarize=lambda since: summary.summarize(since, journal_dir=tmp_path, logs_dir=logs),
                          stock_detail=summary.stock_detail)
    monkeypatch.setenv("MEDIA_PICKS_CLAUDE_BIN", str(_fake_claude(tmp_path, json.dumps(_verdict("{code}")))))
    out = judge.run(SINCE, ["00631L.TW"], dossier_fn=lambda *a: "本輪資料包", summary_mod=mod,
                    records_fn=lambda: _REC)
    assert out[0]["ok"] is True
    prompt = (tmp_path / "prompt-00631L.TW").read_text()
    assert "補判原話" in prompt and "本輪資料包" in prompt and "- 甲：" in prompt
