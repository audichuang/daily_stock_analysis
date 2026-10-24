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


# ---- push／sync／鎖／detach／summary 的失敗路徑（stub 掉 notify_failure，絕不送 Bark） ----

def _sh(cwd, body, env_extra=None):
    """source job 腳本後跑 body；notify_failure 換成寫檔，LOG 預設丟掉。"""
    prelude = (f'source "{JOB}"; LOG="${{LOG:-/dev/null}}"; '
               'notify_failure() { printf "%s\\n" "$*" >>"${NOTIFY_FILE:-/dev/null}"; }; ')
    import os
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(["bash", "-c", prelude + body], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=90, env=env)


def _advance_origin(tmp_path, repo, filename, content):
    """另一個 clone 往 origin/develop 推一個 commit，模擬別處先推了 develop。"""
    other = tmp_path / "other"
    remote = _git(repo, "remote", "get-url", "origin")
    if not other.exists():
        _git(tmp_path, "clone", "-q", remote, str(other))
        _git(other, "config", "user.email", "o@example.com")
        _git(other, "config", "user.name", "o")
    path = other / filename
    path.parent.mkdir(exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", f"other {filename}")
    _git(other, "push", "-q", "origin", "develop")


def _remote_files(repo, ref="develop"):
    return set(_git(repo, "ls-tree", "-r", "--name-only", f"origin/{ref}").split())


def test_commit_journal_rebases_and_retries_when_push_rejected(repo, tmp_path):
    _advance_origin(tmp_path, repo, "journal/ptt-picks.jsonl", '{"theirs": 1}\n')
    with (repo / "journal" / "media-picks.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"mine": 1}\n')

    assert _commit_journal(repo) == "ok"
    _git(repo, "fetch", "-q", "origin")
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "rev-parse", "origin/develop")
    assert _remote_files(repo) >= {"journal/ptt-picks.jsonl", "journal/media-picks.jsonl"}
    assert _git(repo, "status", "--porcelain") == ""


def test_commit_journal_fails_and_aborts_rebase_on_conflict(repo, tmp_path):
    _advance_origin(tmp_path, repo, "journal/media-picks.jsonl", '{"theirs": 1}\n')   # 同一檔同一行 → 衝突
    (repo / "journal" / "media-picks.jsonl").write_text('{"mine": 1}\n', encoding="utf-8")

    assert _commit_journal(repo) == "fail"
    assert not (repo / ".git" / "rebase-merge").exists() and not (repo / ".git" / "rebase-apply").exists()
    assert _git(repo, "branch", "--show-current") == "develop"


def test_commit_journal_pushes_leftover_local_commit_without_new_changes(repo):
    with (repo / "journal" / "media-picks.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"leftover": 1}\n')
    _git(repo, "commit", "-q", "-am", "journal: leftover")     # 上一晚 push 失敗留下的
    assert _git(repo, "status", "--porcelain") == ""

    assert _commit_journal(repo) == "ok"
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "ls-remote", "origin", "develop").split()[0]


def test_sync_develop_rebases_when_only_journal_commits_are_local(repo, tmp_path):
    with (repo / "journal" / "media-picks.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"mine": 1}\n')
    _git(repo, "commit", "-q", "-am", "journal: mine")
    _advance_origin(tmp_path, repo, "other.txt", "changed upstream\n")

    r = _sh(repo, "sync_develop")
    assert r.returncode == 0, r.stderr
    assert _git(repo, "log", "--format=%s", "-3").splitlines()[0] == "journal: mine"
    assert (repo / "other.txt").read_text(encoding="utf-8") == "changed upstream\n"
    assert _git(repo, "merge-base", "--is-ancestor", "origin/develop", "HEAD") == ""


def test_sync_develop_refuses_rebase_when_local_commit_touches_non_journal(repo, tmp_path):
    (repo / "other.txt").write_text("local edit\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "local non-journal")
    _advance_origin(tmp_path, repo, "journal/ptt-picks.jsonl", "{}\n")
    head = _git(repo, "rev-parse", "HEAD")

    r = _sh(repo, "sync_develop")
    assert r.returncode == 1
    assert "other.txt" in r.stderr
    assert _git(repo, "rev-parse", "HEAD") == head      # 沒被動過


def test_sync_develop_fast_forwards_when_nothing_local(repo, tmp_path):
    _advance_origin(tmp_path, repo, "other.txt", "x\n")
    assert _sh(repo, "sync_develop").returncode == 0
    assert (repo / "other.txt").read_text(encoding="utf-8") == "x\n"


def _lock_run(tmp_path, holder_pid, age_s, keep_log, stale_s=100):
    import os
    lock = tmp_path / "logs" / ".job.lock"
    lock.mkdir(parents=True, exist_ok=True)
    if holder_pid is not None:
        (lock / "pid").write_text(str(holder_pid))
    t = datetime.now().timestamp() - age_s
    os.utime(lock, (t, t))
    log = tmp_path / "job.log"
    notify = tmp_path / "notify.txt"
    r = _sh(tmp_path, f'acquire_lock logs/.job.lock 媒體點名 {stale_s} {keep_log} "TITLE"; echo acquired',
            {"LOG": str(log), "NOTIFY_FILE": str(notify)})
    return r, log, notify, lock


@pytest.fixture()
def live_holder():
    p = subprocess.Popen(["sleep", "60"])
    yield p.pid
    p.kill()
    p.wait()


def test_acquire_lock_stale_live_holder_fails_and_notifies(tmp_path, live_holder):
    r, log, notify, _ = _lock_run(tmp_path, live_holder, age_s=500, keep_log=1)
    assert r.returncode == 1 and "acquired" not in r.stdout
    assert "FAILED:" in log.read_text(encoding="utf-8")
    assert "已卡住" in notify.read_text(encoding="utf-8") and "TITLE" in notify.read_text(encoding="utf-8")


def test_acquire_lock_fresh_live_holder_skips_and_keeps_log(tmp_path, live_holder):
    r, log, notify, _ = _lock_run(tmp_path, live_holder, age_s=5, keep_log=1)
    assert r.returncode == 0 and "acquired" not in r.stdout
    assert "本次不重複跑" in log.read_text(encoding="utf-8")
    assert not notify.exists()


def test_acquire_lock_skip_removes_log_unless_asked_to_keep(tmp_path, live_holder):
    log = tmp_path / "job.log"
    log.write_text("x", encoding="utf-8")
    r, log, _, _ = _lock_run(tmp_path, live_holder, age_s=5, keep_log=0)
    assert r.returncode == 0
    assert not log.exists()


def test_acquire_lock_dead_holder_is_reacquired(tmp_path):
    dead = subprocess.Popen(["true"])
    dead.wait()
    r, _, notify, lock = _lock_run(tmp_path, dead.pid, age_s=5000, keep_log=1)
    assert r.returncode == 0 and "acquired" in r.stdout
    assert not notify.exists()
    assert not lock.exists()      # EXIT trap 清掉了本輪的鎖


def test_pick_run_id_honours_env_and_detach_prints_exact_log_path(tmp_path):
    r = _sh(tmp_path, 'pick_run_id', {"MEDIA_PICKS_RUN_ID": "20261101_230000"})
    assert r.stdout.strip() == "20261101_230000"
    assert _sh(tmp_path, 'unset MEDIA_PICKS_RUN_ID; pick_run_id').stdout.strip() != ""

    body = ('spawn_detached() { echo "spawn script=$1 id=$MEDIA_PICKS_RUN_ID" >&2; DETACHED_PID=4242; }; '
            'unset MEDIA_PICKS_RUN_ID; detach_media /x/media_picks_job.sh')
    r = _sh(tmp_path, body)
    assert r.returncode == 0
    path_line = next(ln for ln in r.stdout.splitlines() if ln.startswith("log: "))
    run_id = path_line.removeprefix("log: logs/media_picks_job_").removesuffix(".log")
    assert f"spawn script=/x/media_picks_job.sh id={run_id}" in r.stderr     # 子行程拿到同一個 id
    assert "pid 4242" in r.stdout


def test_summarize_run_logs_since_even_when_summary_fails(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "uv").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (bindir / "uv").chmod(0o755)
    log = tmp_path / "job.log"
    r = _sh(tmp_path, 'summarize_run 2026-10-26T23:00:00+0800 "$PWD/s.json"; echo rc=$?',
            {"LOG": str(log), "PATH": f"{bindir}:/usr/bin:/bin"})
    text = log.read_text(encoding="utf-8")
    assert "rc=1" in r.stdout
    assert "RESULT since=2026-10-26T23:00:00+0800" in text and "RESULT summary=none" in text


def test_sync_develop_aborts_rebase_on_conflict(repo, tmp_path):
    (repo / "journal" / "media-picks.jsonl").write_text('{"mine": 1}\n', encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "journal: mine")
    _advance_origin(tmp_path, repo, "journal/media-picks.jsonl", '{"theirs": 1}\n')   # 同一行 → 衝突
    head = _git(repo, "rev-parse", "HEAD")

    r = _sh(repo, "sync_develop")
    assert r.returncode == 1
    assert not (repo / ".git" / "rebase-merge").exists() and not (repo / ".git" / "rebase-apply").exists()
    assert _git(repo, "rev-parse", "HEAD") == head


# ---- 只推 journal 的守門：非 journal 的本地 commit、切分支、髒工作樹 ----

def _origin_head(repo):
    return _git(repo, "ls-remote", "origin", "develop").split()[0]


def _human_commit(repo):
    (repo / "other.txt").write_text("human work\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "human: non-journal")


def test_commit_journal_refuses_to_push_human_commit_alongside_journal_change(repo):
    _human_commit(repo)                       # ff-only 對它回「Already up to date」，sync 的守門不會跑
    before = _origin_head(repo)
    with (repo / "journal" / "media-picks.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"mine": 1}\n')

    assert _commit_journal(repo) == "fail"
    assert _origin_head(repo) == before
    assert "journal: media picks" not in _git(repo, "log", "--format=%s")


def test_commit_journal_refuses_to_push_human_commit_without_journal_change(repo):
    _human_commit(repo)
    before = _origin_head(repo)

    assert _commit_journal(repo) == "fail"
    assert _origin_head(repo) == before


def test_commit_journal_refuses_rename_into_journal(repo):
    # git log 預設偵測改名、只列新路徑；把 other.txt 搬進 journal/ 等於刪掉它，不能當成只動 journal/
    _git(repo, "mv", "other.txt", "journal/other.txt")
    _git(repo, "commit", "-q", "-m", "move")
    before = _origin_head(repo)

    assert _commit_journal(repo) == "fail"
    assert _origin_head(repo) == before


def test_commit_journal_refuses_merge_commit_ahead(repo):
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "journal" / "ptt-picks.jsonl").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "side")
    _git(repo, "checkout", "-q", "develop")
    (repo / "journal" / "media-picks.jsonl").write_text('{"d": 1}\n', encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "dev")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    before = _origin_head(repo)

    assert _commit_journal(repo) == "fail"
    assert _origin_head(repo) == before


def test_commit_journal_refuses_when_branch_switched(repo):
    _git(repo, "checkout", "-q", "-b", "feature")
    with (repo / "journal" / "media-picks.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"mine": 1}\n')
    before_head = _git(repo, "rev-parse", "HEAD")
    before_origin = _origin_head(repo)

    assert _commit_journal(repo) == "fail"
    assert _git(repo, "rev-parse", "HEAD") == before_head       # feature 上沒有多一個 commit
    assert _origin_head(repo) == before_origin


def test_commit_journal_fails_safely_on_dirty_tree_when_push_rejected(repo, tmp_path):
    _advance_origin(tmp_path, repo, "journal/ptt-picks.jsonl", '{"theirs": 1}\n')
    (repo / "other.txt").write_text("uncommitted human edit\n", encoding="utf-8")   # tracked 且未 commit
    with (repo / "journal" / "media-picks.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"mine": 1}\n')

    assert _commit_journal(repo) == "fail"
    assert not (repo / ".git" / "rebase-merge").exists() and not (repo / ".git" / "rebase-apply").exists()
    assert (repo / "other.txt").read_text(encoding="utf-8") == "uncommitted human edit\n"
    assert _git(repo, "stash", "list") == ""


def test_sync_develop_fails_safely_on_dirty_tree(repo, tmp_path):
    with (repo / "journal" / "media-picks.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"mine": 1}\n')
    _git(repo, "commit", "-q", "-am", "journal: mine")
    _advance_origin(tmp_path, repo, "other.txt", "upstream\n")
    (repo / "journal" / "ptt-picks.jsonl").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", ".")                                       # 髒（已暫存）
    r = _sh(repo, "sync_develop")
    assert r.returncode == 1
    assert not (repo / ".git" / "rebase-merge").exists() and not (repo / ".git" / "rebase-apply").exists()
    assert _git(repo, "stash", "list") == ""


# ---- push_journal_cli（--push-journal 的本體）：只推 journal commit，最後一行 stdout 是結果 ----

def _push_cli(repo):
    r = _sh(repo, "push_journal_cli")
    return r.returncode, r.stdout.strip(), r.stderr


def _journal_commit(repo, line='{"mine": 1}\n'):
    with (repo / "journal" / "media-picks.jsonl").open("a", encoding="utf-8") as f:
        f.write(line)
    _git(repo, "commit", "-q", "-am", "journal: mine")


def test_push_journal_cli_pushes_journal_only_commit(repo):
    _journal_commit(repo)
    assert _push_cli(repo)[:2] == (0, "push ok")
    assert _origin_head(repo) == _git(repo, "rev-parse", "HEAD")


def test_push_journal_cli_reports_none_when_nothing_ahead(repo):
    before = _origin_head(repo)
    assert _push_cli(repo)[:2] == (0, "push none")
    assert _origin_head(repo) == before


def test_push_journal_cli_refuses_human_commit(repo):
    _human_commit(repo)
    before = _origin_head(repo)
    rc, out, err = _push_cli(repo)
    assert rc == 1 and out.startswith("push refused: ") and "other.txt" in out and "other.txt" in err
    assert _origin_head(repo) == before


def test_push_journal_cli_refuses_human_commit_mixed_with_journal(repo):
    _journal_commit(repo)
    _human_commit(repo)
    before = _origin_head(repo)
    assert _push_cli(repo)[1].startswith("push refused: ")
    assert _origin_head(repo) == before


def test_push_journal_cli_refuses_merge_commit(repo):
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "journal" / "ptt-picks.jsonl").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "side")
    _git(repo, "checkout", "-q", "develop")
    _journal_commit(repo)
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    before = _origin_head(repo)
    rc, out, _ = _push_cli(repo)
    assert rc == 1 and "merge" in out and out.startswith("push refused: ")
    assert _origin_head(repo) == before


def test_push_journal_cli_refuses_off_develop(repo):
    _git(repo, "checkout", "-q", "-b", "feature")
    _journal_commit(repo)
    before = _origin_head(repo)
    rc, out, _ = _push_cli(repo)
    assert rc == 1 and out.startswith("push refused: ") and "feature" in out
    assert _origin_head(repo) == before


def test_push_journal_cli_fails_and_aborts_rebase_on_conflict(repo, tmp_path):
    _journal_commit(repo, '{"mine": 1}\n')
    _advance_origin(tmp_path, repo, "journal/media-picks.jsonl", '{"theirs": 1}\n')   # 同一行 → 衝突
    before = _origin_head(repo)
    rc, out, _ = _push_cli(repo)
    assert (rc, out) == (1, "push failed")
    assert _origin_head(repo) == before
    assert not (repo / ".git" / "rebase-merge").exists() and not (repo / ".git" / "rebase-apply").exists()


def test_push_journal_cli_stdout_is_a_single_line_and_main_dispatches_it(repo):
    _human_commit(repo)
    r = _sh(repo, "push_journal_cli")
    assert len(r.stdout.splitlines()) == 1
    body = _sh(repo, "declare -f main").stdout
    assert body.index("--push-journal") < body.index("--detach") < body.index("acquire_lock")


def test_push_journal_cli_rebases_when_push_rejected(repo, tmp_path):
    _advance_origin(tmp_path, repo, "journal/ptt-picks.jsonl", '{"theirs": 1}\n')   # 別處先推，不衝突
    _journal_commit(repo)
    assert _push_cli(repo)[:2] == (0, "push ok")
    _git(repo, "fetch", "-q", "origin")
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "rev-parse", "origin/develop")
    assert _remote_files(repo) >= {"journal/ptt-picks.jsonl", "journal/media-picks.jsonl"}


def test_push_journal_cli_ignores_dirty_tree_when_push_is_accepted(repo):
    _journal_commit(repo)
    (repo / "other.txt").write_text("uncommitted human edit\n", encoding="utf-8")    # 髒工作樹不該擋 push
    assert _push_cli(repo)[:2] == (0, "push ok")
    assert (repo / "other.txt").read_text(encoding="utf-8") == "uncommitted human edit\n"


def test_push_journal_flag_runs_end_to_end_without_lock_or_log(repo):
    """把腳本複製進暫存 repo 當根目錄再直接執行：驗證 main 的分派、exit code，且不取鎖、不建 log、不通知。"""
    import shutil
    (repo / "scripts").mkdir()
    for name in ("media_picks_job.sh", "daily_report.sh"):
        shutil.copy(ROOT / "scripts" / name, repo / "scripts" / name)
    bin_dir = repo / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(f'#!/bin/sh\necho curl >>"{repo}/curl.called"\n', encoding="utf-8")
    (bin_dir / "curl").chmod(0o755)

    def run():
        import os
        return subprocess.run(["bash", "scripts/media_picks_job.sh", "--push-journal"], cwd=repo, capture_output=True,
                              text=True, timeout=60, env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"})

    _journal_commit(repo)
    r = run()
    assert (r.returncode, r.stdout.strip()) == (0, "push ok")
    assert _origin_head(repo) == _git(repo, "rev-parse", "HEAD")
    r = run()
    assert (r.returncode, r.stdout.strip()) == (0, "push none")
    _human_commit(repo)
    r = run()
    assert r.returncode == 1 and r.stdout.startswith("push refused: ") and len(r.stdout.splitlines()) == 1
    assert not (repo / "logs").exists() and not (repo / "curl.called").exists()
