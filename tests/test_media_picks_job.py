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
GOOD_DATA = {"vs_ma20_pct": 3.0, "vs_ma60_pct": 8.0, "revenue_yoy_3m": [25.0, 30.0, 28.0]}


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


def test_bullish_counts_distinct_speakers_not_shows(tmp_path):
    s = _summarize(tmp_path, [
        _pick(show="瘋狂股市福利社", speaker="李四"),
        _pick(show="理周TV", speaker="李四"),          # 同一位投顧在兩個節目
        _pick(show="錢線百分百", speaker=None),         # 沒有講者 → 節目當單位
        _pick(show="TVBS金臨天下", speaker="", stance="bearish"),
    ])
    (top,) = s["bullish"]
    assert top["bull_voices"] == 2
    assert top["bear_voices"] == 1
    assert top["shows"] == sorted(["瘋狂股市福利社", "理周TV", "錢線百分百"])


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


@pytest.mark.parametrize("data, expected", [
    (GOOD_DATA, True),
    (None, False),
    ({**GOOD_DATA, "vs_ma60_pct": -0.5}, False),
    ({**GOOD_DATA, "revenue_yoy_3m": [40.0, 30.0, 25.0]}, False),  # 降速超過 10 個百分點
    ({**GOOD_DATA, "revenue_yoy_3m": [25.0, None, 28.0]}, False),
])
def test_data_ok(data, expected):
    assert summary_mod.data_ok(data) is expected


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
