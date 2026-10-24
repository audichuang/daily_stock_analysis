# -*- coding: utf-8 -*-
"""23:00 媒體點名排程：scripts/media_picks_summary.py 的取列與統計、scripts/media_picks_job.sh 的 journal commit。

job 腳本只 source、不直接執行（直接執行會同步 develop、跑真正的擷取並 push）。
"""
import importlib.util
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JOB = ROOT / "scripts" / "media_picks_job.sh"
_spec = importlib.util.spec_from_file_location("media_picks_summary", ROOT / "scripts" / "media_picks_summary.py")
summary_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(summary_mod)

SINCE = datetime.fromisoformat("2026-10-26T23:00:00+08:00")


def _pick(**kw):
    row = {"video_id": "v1", "show": "錢線百分百", "kind": "tv", "name": "台積電", "name_said": "台積電",
           "stock_code": "2330.TW", "resolve": "exact", "code_llm": "2330", "stance": "bullish",
           "speaker": "張三", "data": None, "extracted_at": "2026-10-26T23:20:00+08:00"}
    row.update(kw)
    return row


def _write(path: Path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _summarize(tmp_path, media, ptt=(), review=()):
    _write(tmp_path / "media-picks.jsonl", media)
    _write(tmp_path / "ptt-picks.jsonl", ptt)
    if review:
        _write(tmp_path / "media-picks-review.jsonl", review)
    return summary_mod.summarize(SINCE, journal_dir=tmp_path, transcript_dir=tmp_path / "transcripts")


def test_keeps_rows_after_midnight_and_drops_earlier_runs(tmp_path):
    s = _summarize(tmp_path, [
        _pick(video_id="old1", extracted_at="2026-10-26T08:35:00+08:00"),  # 同一天早上補跑的上一輪
        _pick(video_id="old2", extracted_at="2026-10-26T08:36:00+08:00"),
        _pick(video_id="late", extracted_at="2026-10-27T00:10:00+08:00"),  # 本輪跨過午夜
        _pick(video_id="on_time"),
    ])
    assert s["media"]["episodes"] == 2
    assert s["media"]["picks"] == 2


def test_stocks_count_distinct_speakers_and_keep_every_stance(tmp_path):
    s = _summarize(tmp_path, [
        _pick(show="瘋狂股市福利社", speaker="李四", reason="訂單滿到明年"),
        _pick(show="理周TV", speaker="李四"),          # 同一位投顧在兩個節目
        _pick(show="錢線百分百", speaker=None),         # 沒有講者 → 節目當單位
        _pick(show="TVBS金臨天下", speaker="", stance="bearish"),
        _pick(show="財報狗", speaker="Sky", stance="neutral", kind="research"),
        _pick(stock_code="2317.TW", name="鴻海", stance="avoid", speaker="王五"),  # 只有看空也要收
    ])
    by_code = {st["code"]: st for st in s["stocks"]}
    tsmc = by_code["2330.TW"]
    assert (tsmc["bull_voices"], tsmc["bear_voices"], tsmc["neutral_voices"]) == (2, 1, 1)
    assert len(tsmc["voices"]) == 5  # 原話逐筆保留，不因講者去重而丟掉
    assert tsmc["voices"][0]["reason"] == "訂單滿到明年"
    assert by_code["2317.TW"]["bear_voices"] == 1
    assert [st["code"] for st in s["stocks"]] == ["2330.TW", "2317.TW"]


def test_history_uses_only_rows_before_this_round(tmp_path):
    s = _summarize(tmp_path, [
        _pick(date="2026-10-01", speaker="甲", data={"close": 80.0, "as_of": "2026-09-30"},
              extracted_at="2026-10-01T23:30:00+08:00"),                        # 超過 7 天：只算首次
        _pick(date="2026-10-22", speaker="乙", stance="bearish", extracted_at="2026-10-22T23:30:00+08:00"),
        _pick(date="2026-10-23", speaker="丙", data={"close": 90.0, "as_of": "2026-10-23"},
              extracted_at="2026-10-23T23:30:00+08:00"),                        # 首次收盤要取最早那筆
        _pick(date="2026-10-26", speaker="丁", data={"close": 100.0, "as_of": "2026-10-26"}),  # 本輪
    ])
    (st,) = s["stocks"]
    h = st["history"]
    assert h["first_named"] == "2026-10-01"
    assert h["named_days_7d"] == 2
    assert (h["prior_bull_voices"], h["prior_bear_voices"]) == (2, 1)
    assert h["since_first_pct"] == 25.0
    assert st["bull_voices"] == 1  # 之前的列不混進本輪


def test_history_is_none_for_first_mention_and_ptt_is_linked(tmp_path):
    s = _summarize(tmp_path, [_pick()], ptt=[
        {"article_id": "M.1", "stock_code": "2330.TW", "resolve": "exact", "reason": "長多",
         "extracted_at": "2026-10-26T23:40:00+08:00"},
    ])
    (st,) = s["stocks"]
    assert st["history"] is None
    assert st["ptt"] == ["M.1"]
    assert s["ptt"][0]["reason"] == "長多"


def test_index_gives_full_line_from_two_voices_and_short_line_for_one(tmp_path):
    s = _summarize(tmp_path, [
        _pick(speaker="甲", theme="CoWoS", data={"vs_ma20_pct": 3.0, "revenue_yoy_3m": [1, 2, 30.0]}),
        _pick(speaker="乙", stance="bearish"),
        _pick(stock_code="2317.TW", name="鴻海", speaker="丙", kind="research", theme="AI伺服器"),
    ])
    lines = {ln.split("｜")[0]: ln for ln in summary_mod._index(s).splitlines() if ln.startswith("- ")}
    assert "多 1 空 1 中 0" in lines["- 台積電 2330.TW"]
    assert "營收 YoY 30.0" in lines["- 台積電 2330.TW"]
    assert lines["- 鴻海 2317.TW"] == "- 鴻海 2317.TW｜多｜research｜AI伺服器｜新出現"


def test_code_detail_has_only_that_stock_and_its_ptt(tmp_path):
    s = _summarize(tmp_path, [
        _pick(reason="CoWoS 供不應求"),
        _pick(stock_code="2317.TW", name="鴻海", reason="GB300 出貨"),
    ], ptt=[
        {"article_id": "M.1", "title": "[標的] 2330 台積電 多", "stock_code": "2330.TW", "resolve": "exact",
         "reason": "先進製程", "extracted_at": "2026-10-26T23:40:00+08:00"},
        {"article_id": "M.2", "title": "[標的] 2317 鴻海 空", "stock_code": "2317.TW", "resolve": "exact",
         "reason": "毛利太低", "extracted_at": "2026-10-26T23:40:00+08:00"},
    ])
    out = summary_mod.stock_detail(s, "2330.TW")
    assert "CoWoS 供不應求" in out and "先進製程" in out
    assert "GB300" not in out and "毛利太低" not in out
    assert summary_mod.stock_detail(s, "9999.TW") == "本輪沒有人點名 9999.TW"


def test_review_lists_only_uncertain_codes_and_marks_reviewed(tmp_path):
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts" / "v1.txt").write_text("逐字稿", encoding="utf-8")
    s = _summarize(
        tmp_path,
        [
            _pick(),
            _pick(name_said="上權", name="上詮", stock_code="3363.TWO", resolve="code_mismatch"),
            _pick(name_said="台化", name="台灣化學纖維", stock_code=None, resolve="unresolved"),
            _pick(name_said="建頂", stock_code="6533.TW", resolve="fuzzy"),
            _pick(resolve="no_picks", stock_code=None),
        ],
        review=[{"video_id": "v1", "name_said": "上權", "stock_code": "3363.TWO", "verdict": "confirm"}],
    )
    by_said = {r["name_said"]: r for r in s["review"]}
    assert set(by_said) == {"上權", "台化", "建頂"}
    assert by_said["上權"]["already_reviewed"] is True
    assert by_said["台化"]["already_reviewed"] is False
    assert by_said["台化"]["transcript"].endswith("v1.txt")
    assert s["media"]["picks"] == 4  # no_picks 不算點名


# ---- media_picks_job.sh ----

def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "develop", str(remote))
    _git(tmp_path, "init", "-q", "-b", "develop", str(work))
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    (work / "journal").mkdir()
    (work / "journal" / "media-picks.jsonl").write_text("{}\n", encoding="utf-8")
    (work / "other.txt").write_text("a\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-q", "origin", "develop")
    return work


def _commit_journal(cwd):
    r = subprocess.run(["bash", "-c", f'source "{JOB}"; LOG=/dev/null; commit_journal'],
                       cwd=cwd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_job_script_is_valid_bash():
    assert subprocess.run(["bash", "-n", str(JOB)]).returncode == 0


def test_sourcing_job_does_not_run_main(tmp_path):
    r = subprocess.run(["bash", "-c", f'cd "{tmp_path}"; source "{JOB}"; pwd -P; ls -A; declare -F main commit_journal'],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert r.stdout.split() == [str(tmp_path.resolve()), "main", "commit_journal"]


def test_commit_journal_commits_only_journal_files(repo):
    with (repo / "journal" / "media-picks.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"new": 1}\n')
    (repo / "journal" / "ptt-picks.jsonl").write_text('{"ptt": 1}\n', encoding="utf-8")  # 第一次出現的檔
    (repo / "other.txt").write_text("staged change\n", encoding="utf-8")
    _git(repo, "add", "other.txt")

    assert _commit_journal(repo) == "ok"
    assert set(_git(repo, "show", "--name-only", "--format=", "HEAD").split()) == {
        "journal/media-picks.jsonl", "journal/ptt-picks.jsonl"}
    assert _git(repo, "log", "-1", "--format=%s").startswith("journal: media picks ")
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "ls-remote", "origin", "develop").split()[0]
    assert _git(repo, "diff", "--cached", "--name-only") == "other.txt"   # 別的暫存原封不動


def test_commit_journal_reports_none_when_unchanged(repo):
    head = _git(repo, "rev-parse", "HEAD")
    assert _commit_journal(repo) == "none"
    assert _git(repo, "rev-parse", "HEAD") == head
