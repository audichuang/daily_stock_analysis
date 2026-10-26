# -*- coding: utf-8 -*-
"""23:00 媒體點名排程：scripts/media_picks_summary.py 的取列與統計、scripts/media_picks_job.sh 的 journal commit。

job 腳本只 source、不直接執行（直接執行會同步 develop、跑真正的擷取並 push）。
"""
import importlib.util
import json
import os
import subprocess
import time
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


@pytest.mark.parametrize("age_s, acquired", [(0, False), (5000, True)])
def test_acquire_lock_without_pid_waits_for_initialization_but_recovers_old_lock(tmp_path, age_s, acquired):
    r, log, notify, lock = _lock_run(tmp_path, None, age_s=age_s, keep_log=1)
    assert r.returncode == 0, r.stderr
    assert ("acquired" in r.stdout) is acquired
    assert lock.exists() is not acquired
    assert not notify.exists()
    if not acquired:
        assert "本次不重複跑" in log.read_text(encoding="utf-8")


def _wait_until(predicate):
    deadline = time.monotonic() + 30
    while not predicate():
        assert time.monotonic() < deadline, "等待鎖競態測試的同步點逾時"
        time.sleep(0.01)


def test_acquire_lock_serializes_two_dead_owner_recoveries(tmp_path):
    lock = tmp_path / "lock"
    lock.mkdir()
    dead = subprocess.Popen(["true"])
    dead.wait()
    (lock / "pid").write_text(str(dead.pid), encoding="utf-8")
    children = []

    def start(name):
        # 舊實作會在刪鎖前停住；依序放行兩個已讀到死 PID 的行程，穩定重現後來者刪掉新鎖。
        body = f'''
source "{JOB}"
LOG=/dev/null
notify_failure() {{ echo unexpected-notification >&2; }}
rm() {{
  if [[ "$*" == "-rf $PWD/lock" && ! -e "$PWD/{name}.remove" ]]; then
    : >"$PWD/{name}.recovering"
    while [[ ! -e "$PWD/{name}.remove" ]]; do sleep 0.01; done
  fi
  command rm "$@"
}}
acquire_lock "$PWD/lock" 測試 100 1
echo $$ >"$PWD/{name}.acquired"
while [[ ! -e "$PWD/release" ]]; do sleep 0.01; done
'''
        child = subprocess.Popen(["bash", "-c", body], cwd=tmp_path, env={**os.environ, "BASH_ENV": ""},
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        children.append(child)
        return child

    try:
        start("a")
        _wait_until(lambda: (tmp_path / "a.recovering").exists() or (tmp_path / "a.acquired").exists())
        second = start("b")
        if (tmp_path / "a.recovering").exists():
            _wait_until(lambda: (tmp_path / "b.recovering").exists())
            (tmp_path / "a.remove").touch()
            _wait_until(lambda: (tmp_path / "a.acquired").exists())
            (tmp_path / "b.remove").touch()
        _wait_until(lambda: second.poll() is not None or (tmp_path / "b.acquired").exists())
        owners = list(tmp_path.glob("*.acquired"))
        assert len(owners) == 1, f"同一把鎖被兩個行程取得：{owners}"
        assert (lock / "pid").read_text().strip() == owners[0].read_text().strip()
    finally:
        for name in ("a.remove", "b.remove", "release"):
            (tmp_path / name).touch()
        for child in children:
            child.communicate(timeout=30)
    assert not lock.exists()


def test_acquire_lock_exit_does_not_remove_another_owner(tmp_path, live_holder):
    lock = tmp_path / "lock"
    r = _sh(tmp_path, f'acquire_lock "$PWD/lock" 測試 100 1; echo {live_holder} >"$PWD/lock/pid"')
    assert r.returncode == 0, r.stderr
    assert (lock / "pid").read_text().strip() == str(live_holder)


def test_acquire_lock_creation_failure_never_runs_protected_work(tmp_path):
    r = _sh(tmp_path, 'acquire_lock "$PWD/missing/lock" 測試 100 1; echo acquired')
    assert r.returncode == 1
    assert "acquired" not in r.stdout


@pytest.mark.parametrize("action", ["acquire", "release"])
def test_lock_transitions_check_owner_under_persistent_guard(tmp_path, action):
    import fcntl

    lock = tmp_path / "lock"
    lock.mkdir()
    (lock / "pid").write_text("99999999\n", encoding="utf-8")
    guard = tmp_path / "lock.guard"
    with guard.open("a") as handle:
        inode = guard.stat().st_ino
        fcntl.flock(handle, fcntl.LOCK_EX)
        body = f'''
source "{JOB}"
LOG=/dev/null
LOCK="$PWD/lock"
notify_failure() {{ echo unexpected-notification >&2; }}
[[ "{action}" != release ]] || echo $$ >"$LOCK/pid"
: >"$PWD/ready"
if [[ "{action}" == acquire ]]; then
  acquire_lock "$LOCK" 測試 100 1
else
  release_lock
fi
echo transitioned
'''
        child = subprocess.Popen(["bash", "-c", body], cwd=tmp_path, env={**os.environ, "BASH_ENV": ""},
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            _wait_until(lambda: (tmp_path / "ready").exists())
            # 只有守門檔解鎖後才能讀 PID；期間換持有者，放行後必須保留新持有者的鎖。
            with pytest.raises(subprocess.TimeoutExpired):
                child.wait(timeout=0.1)
            (lock / "pid").write_text(str(os.getpid()), encoding="utf-8")
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            out, err = child.communicate(timeout=30)
    assert child.returncode == 0, err
    assert ("transitioned" in out) is (action == "release")
    assert (lock / "pid").read_text().strip() == str(os.getpid())
    assert guard.stat().st_ino == inode


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


@pytest.mark.parametrize("entrypoint, result", [("push_journal_cli", "push ok"), ("commit_journal", "ok")])
def test_journal_push_pins_validated_sha_when_local_develop_moves(repo, entrypoint, result):
    _journal_commit(repo)
    validated = _git(repo, "rev-parse", "HEAD")
    r = _sh(repo, f'''
git_net() {{
  if [[ "$1" == push ]]; then
    printf 'human work\\n' >other.txt
    command git commit -q -am 'human: raced validation'
  fi
  command git "$@" >&2
}}
{entrypoint}
''')
    assert (r.returncode, r.stdout.strip()) == (0, result), r.stderr
    assert _origin_head(repo) == validated
    assert _git(repo, "rev-parse", "HEAD") != validated
    assert _git(repo, "show", "origin/develop:other.txt") == "a"


@pytest.mark.parametrize("entrypoint, result", [("push_journal_cli", "push ok"), ("commit_journal", "ok")])
def test_journal_push_validates_captured_range_when_head_moves_during_check(repo, entrypoint, result):
    _journal_commit(repo)
    validated = _git(repo, "rev-parse", "HEAD")
    r = _sh(repo, f'''
checks=0
git() {{
  if [[ "$1" == rev-list ]]; then
    # git rev-list 在 command substitution 的子 shell，計數寫檔以跨越兩次驗證。
    checks=$(cat .git/check-count 2>/dev/null || echo 0)
    echo $((checks + 1)) >.git/check-count
    if (( checks == 1 )); then
      printf 'human work\\n' >other.txt
      command git commit -q -am 'human: raced range check'
    fi
  fi
  command git "$@"
}}
{entrypoint}
''')
    assert (r.returncode, r.stdout.strip()) == (0, result), r.stderr
    assert _git(repo, "rev-parse", "HEAD") != validated
    assert _origin_head(repo) == validated


@pytest.mark.parametrize("entrypoint, result", [("push_journal_cli", "push failed"), ("commit_journal", "fail")])
def test_journal_push_revalidates_after_rebase(repo, tmp_path, entrypoint, result):
    _journal_commit(repo)
    _advance_origin(tmp_path, repo, "journal/ptt-picks.jsonl", '{}\n')
    remote_before = _origin_head(repo)
    r = _sh(repo, f'''
git_net() {{
  command git "$@" >&2 || return $?
  if [[ "$1" == pull ]]; then
    printf 'human work\\n' >other.txt
    command git commit -q -am 'human: raced rebase' >&2
  fi
}}
{entrypoint}
''')
    assert r.stdout.strip() == result, r.stderr
    assert r.returncode == (1 if entrypoint == "push_journal_cli" else 0)
    assert _origin_head(repo) == remote_before
    assert "other.txt" in r.stderr


def test_journal_push_lease_uses_validated_origin_even_if_tracking_ref_moves(repo):
    _journal_commit(repo)
    intermediate = _git(repo, "rev-parse", "HEAD")
    _journal_commit(repo, '{"second": 2}\n')
    r = _sh(repo, f'''
git_net() {{
  if [[ "$1" == push ]]; then
    command git push -q origin "{intermediate}:refs/heads/develop" >&2
    command git fetch -q origin >&2
  elif [[ "$1" == pull ]]; then
    echo rebase-attempted >&2
    return 1
  fi
  command git "$@" >&2
}}
push_journal_cli
''')
    assert (r.returncode, r.stdout.strip()) == (1, "push failed"), r.stderr
    assert "rebase-attempted" in r.stderr
    assert _origin_head(repo) == intermediate


def _feature_branch_ahead(repo):
    """develop 有一個待推的 journal commit；feature 分支（同樣只動 journal/）另外領先，模擬別的 session 的分支。"""
    _journal_commit(repo)
    develop_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "feature")
    _journal_commit(repo, '{"feature": 1}\n')
    feature_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "develop")
    return develop_sha, feature_sha


# 第一次 `git branch --show-current` 回 develop 後立刻切到 feature：模擬分支檢查剛過、主 checkout 就被別的 session 切走。
_SWITCH_AFTER_BRANCH_CHECK = '''
git() {
  if [[ "$1" == branch && "$2" == --show-current && ! -e .git/switched ]]; then
    : >.git/switched
    command git branch --show-current
    command git checkout -q feature >&2
    return 0
  fi
  command git "$@"
}
'''


@pytest.mark.parametrize("entrypoint, result", [("push_journal_cli", "push ok"), ("commit_journal", "ok")])
def test_journal_push_publishes_local_develop_not_head_when_branch_switches(repo, entrypoint, result):
    develop_sha, feature_sha = _feature_branch_ahead(repo)
    r = _sh(repo, _SWITCH_AFTER_BRANCH_CHECK + entrypoint)
    assert _git(repo, "branch", "--show-current") == "feature"   # 切換確實發生在檢查之後
    assert (r.returncode, r.stdout.strip()) == (0, result), r.stderr
    assert _origin_head(repo) == develop_sha                     # 推的是本地 develop，不是 feature
    assert _git(repo, "rev-parse", "feature") == feature_sha


@pytest.mark.parametrize("entrypoint, result", [("push_journal_cli", "push failed"), ("commit_journal", "fail")])
def test_journal_push_retry_refuses_rebase_after_branch_switch(repo, tmp_path, entrypoint, result):
    develop_sha, feature_sha = _feature_branch_ahead(repo)
    _advance_origin(tmp_path, repo, "journal/ptt-picks.jsonl", '{"theirs": 1}\n')
    remote_before = _origin_head(repo)
    r = _sh(repo, f'''
git_net() {{
  command git "$@" >&2
  local rc=$?
  if [[ "$1" == push ]]; then command git checkout -q feature >&2; fi
  if [[ "$1" == pull ]]; then echo rebase-attempted >&2; fi
  return $rc
}}
{entrypoint}
''')
    assert r.stdout.strip() == result, r.stderr
    assert "rebase-attempted" not in r.stderr
    assert _git(repo, "rev-parse", "feature") == feature_sha      # feature 沒被 rebase
    assert _git(repo, "rev-parse", "develop") == develop_sha
    assert _origin_head(repo) == remote_before


def test_push_develop_never_rewinds_when_local_head_is_behind(repo, tmp_path):
    _advance_origin(tmp_path, repo, "other.txt", "new remote work\n")
    _git(repo, "fetch", "-q", "origin")
    remote_before = _origin_head(repo)
    r = _sh(repo, "push_develop")
    assert r.returncode == 0, r.stderr
    assert _origin_head(repo) == remote_before
    assert _git(repo, "rev-parse", "HEAD") == remote_before


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


def test_main_logs_since_right_after_lock_before_extraction():
    # 擷取中途掛掉時 log 裡也要有本輪 since（--judge-since 靠它找出沒判過的輪次）
    body = (ROOT / "scripts" / "media_picks_job.sh").read_text(encoding="utf-8")
    main = body[body.index("\nmain() {"):]
    lock, since, extract = (main.index('acquire_lock "logs/.media_picks_job.lock"'),
                            main.index('log "RESULT since=$run_start"'), main.index("make media-picks"))
    assert lock < since < extract


# ---- 持股標示：holdings.json × 本輪點名 ----

def _holdings_file(tmp_path, *codes, name="holdings.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"as_of": "2026-10-26", "codes": [
        {"code": c, "name": c, "accounts": ["a"], "quantity": 1000} for c in codes]}), encoding="utf-8")
    return p


def _held_summary(tmp_path, media, ptt=(), holdings=None):
    _write(tmp_path / "media-picks.jsonl", media)
    _write(tmp_path / "ptt-picks.jsonl", ptt)
    return summary_mod.summarize(SINCE, journal_dir=tmp_path, transcript_dir=tmp_path / "transcripts", holdings=holdings)


def _ptt(code="2330.TW", stance=None, **kw):
    row = {"article_id": "M.1", "title": "[標的] x", "stock_code": code, "resolve": "exact", "stance": stance,
           "push_up": 1, "push_down": 0, "extracted_at": "2026-10-26T23:40:00+08:00"}
    row.update(kw)
    return row


def test_held_flag_and_holdings_block_counts(tmp_path):
    h = _holdings_file(tmp_path, "2330.TW", "6191.TW")
    s = _held_summary(tmp_path, [
        _pick(speaker="甲"), _pick(speaker="乙", stance="neutral"),
        _pick(stock_code="2317.TW", name="鴻海", speaker="丙"),
    ], ptt=[_ptt(stance="bullish")], holdings=h)
    assert {st["code"]: st["held"] for st in s["stocks"]} == {"2330.TW": True, "2317.TW": False}
    (m,) = s["holdings"]["mentioned"]               # 6191 沒被點名 → 不列
    assert (m["code"], m["bull_voices"], m["bear_voices"], m["neutral_voices"], m["ptt_articles"]) == ("2330.TW", 1, 0, 1, 1)
    assert m["alert"] is False
    assert s["holdings"]["available"] and s["holdings"]["count"] == 2


@pytest.mark.parametrize("stance", ["bearish", "avoid"])
def test_alert_on_bearish_or_avoid_voice(tmp_path, stance):
    s = _held_summary(tmp_path, [_pick(speaker="甲"), _pick(speaker="乙", stance=stance)],
                      holdings=_holdings_file(tmp_path, "2330.TW"))
    assert s["holdings"]["mentioned"][0]["alert"] is True


def test_no_alert_on_neutral_voice_or_non_bear_ptt(tmp_path):
    s = _held_summary(tmp_path, [_pick(stance="neutral")], ptt=[_ptt(stance="neutral"), _ptt(stance="bullish", article_id="M.2")],
                      holdings=_holdings_file(tmp_path, "2330.TW"))
    assert s["holdings"]["mentioned"][0]["alert"] is False


def test_alert_on_bearish_ptt_even_without_tv_mention(tmp_path):
    s = _held_summary(tmp_path, [_pick(stock_code="2317.TW", name="鴻海")], ptt=[_ptt(stance="bearish")],
                      holdings=_holdings_file(tmp_path, "2330.TW"))
    (m,) = s["holdings"]["mentioned"]
    assert (m["code"], m["alert"], m["ptt_articles"], m["ptt_bear_articles"], m["bear_voices"]) == ("2330.TW", True, 1, 1, 0)


def test_index_first_section_in_three_states(tmp_path):
    media = [_pick(speaker="甲", stance="bullish"), _pick(speaker="乙", stance="bearish")]
    mentioned = summary_mod._index(_held_summary(tmp_path, media, holdings=_holdings_file(tmp_path, "2330.TW")))
    assert mentioned.startswith("## 你的持股被點名 1 檔\n- 2330.TW 2330.TW｜多 1 空 1 中 0｜PTT 0｜⚠ 有看空\n") or \
        mentioned.startswith("## 你的持股被點名 1 檔\n- 台積電 2330.TW｜多 1 空 1 中 0｜PTT 0｜⚠ 有看空\n")
    quiet = summary_mod._index(_held_summary(tmp_path, media, holdings=_holdings_file(tmp_path, "6191.TW")))
    assert quiet.startswith("## 你的持股本輪沒有被點名\n")
    missing = summary_mod._index(_held_summary(tmp_path, media, holdings=None))
    assert missing.startswith("## 持股清單取不到\n")
    for text in (mentioned, quiet, missing):
        assert text.index("# 本輪") > text.index("## ")        # 持股段在標題行之前＝第一段


def test_index_line_has_no_alert_marker_when_not_bearish(tmp_path):
    out = summary_mod._index(_held_summary(tmp_path, [_pick()], holdings=_holdings_file(tmp_path, "2330.TW")))
    assert "⚠" not in out


def test_code_detail_prefix_only_for_held(tmp_path):
    s = _held_summary(tmp_path, [_pick(), _pick(stock_code="2317.TW", name="鴻海")],
                      holdings=_holdings_file(tmp_path, "2330.TW"))
    assert summary_mod.stock_detail(s, "2330.TW").startswith("（你持有這檔）\n")
    assert not summary_mod.stock_detail(s, "2317.TW").startswith("（你持有這檔）")


@pytest.mark.parametrize("content", [None, "not json{", '{"error": "boom"}', '{"error": "boom", "codes": []}', '{"codes": "x"}', "[]"])
def test_missing_or_garbled_holdings_file_is_ignored(tmp_path, capsys, content):
    p = tmp_path / "h.json"
    if content is not None:
        p.write_text(content, encoding="utf-8")
    s = _held_summary(tmp_path, [_pick()], holdings=p)
    assert s["holdings"] == {"available": False, "count": 0, "mentioned": []}
    assert s["stocks"][0]["held"] is False
    assert "持股清單" in capsys.readouterr().err


def test_cli_holdings_flag_reaches_index(tmp_path, capsys):
    _write(tmp_path / "media-picks.jsonl", [_pick()])
    _write(tmp_path / "ptt-picks.jsonl", [])
    h = _holdings_file(tmp_path, "2330.TW")
    assert summary_mod.main(["--since", SINCE.isoformat(), "--index", "--journal-dir", str(tmp_path),
                             "--holdings", str(h)]) == 0
    assert capsys.readouterr().out.startswith("## 你的持股被點名 1 檔")


# ---- job：capture_holdings 與 summarize_run 的 --holdings ----

def _stub_uv(tmp_path, script):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "uv").write_text("#!/bin/sh\n" + script, encoding="utf-8")
    (bindir / "uv").chmod(0o755)
    # BASH_ENV 清掉：本機的 toolchain.sh 會在 bash 啟動時把 ~/.local/bin 塞到 PATH 前面，真的 uv 會蓋掉 stub
    return {"PATH": f"{bindir}:/usr/bin:/bin:/opt/homebrew/bin", "LOG": str(tmp_path / "job.log"), "BASH_ENV": ""}


def test_capture_holdings_failure_is_non_fatal_and_logged(tmp_path):
    env = _stub_uv(tmp_path, 'echo \'{"error": "OperationalError: 讀持倉失敗"}\'\nexit 1\n')
    r = _sh(tmp_path, 'capture_holdings "$PWD/h.json"; echo rc=$?', env)
    text = (tmp_path / "job.log").read_text(encoding="utf-8")
    assert "rc=1" in r.stdout
    assert "RESULT holdings=none (" in text and "OperationalError" in text
    assert not (tmp_path / "h.json").exists() and not (tmp_path / "h.json.tmp").exists()


def test_capture_holdings_timeout_is_non_fatal(tmp_path):
    env = _stub_uv(tmp_path, "sleep 30\n")
    env["MEDIA_PICKS_HOLDINGS_TIMEOUT_SECONDS"] = "1"
    r = _sh(tmp_path, 'capture_holdings "$PWD/h.json"; echo rc=$?', env)
    assert "rc=1" in r.stdout
    assert "RESULT holdings=none" in (tmp_path / "job.log").read_text(encoding="utf-8")


def test_capture_holdings_success_logs_path_and_keeps_output(tmp_path):
    env = _stub_uv(tmp_path, 'echo \'{"as_of": "x", "codes": []}\'\n')
    r = _sh(tmp_path, 'capture_holdings "$PWD/h.json"; echo rc=$?', env)
    assert "rc=0" in r.stdout
    assert f"RESULT holdings={tmp_path}/h.json" in (tmp_path / "job.log").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "h.json").read_text(encoding="utf-8"))["as_of"] == "x"


def test_summarize_run_passes_holdings_to_both_invocations_only_when_file_exists(tmp_path):
    argv_log = tmp_path / "argv.txt"
    env = _stub_uv(tmp_path, f'echo "$@" >>"{argv_log}"\n')
    (tmp_path / "h.json").write_text("{}", encoding="utf-8")
    _sh(tmp_path, 'summarize_run 2026-10-26T23:00:00+0800 "$PWD/s.json" "$PWD/h.json"', env)
    calls = argv_log.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 2 and all(f"--holdings {tmp_path}/h.json" in c for c in calls)

    argv_log.unlink()
    _sh(tmp_path, 'summarize_run 2026-10-26T23:00:00+0800 "$PWD/s.json" "$PWD/gone.json"', env)
    _sh(tmp_path, 'summarize_run 2026-10-26T23:00:00+0800 "$PWD/s.json"', env)
    assert "--holdings" not in argv_log.read_text(encoding="utf-8")


def test_main_wires_holdings_step_after_commit_and_before_summary():
    body = JOB.read_text(encoding="utf-8")
    assert body.index("commit_journal 2>>") < body.index('capture_holdings "$holdings"') < body.index('summarize_run "$run_start"')
    assert 'capture_holdings "$holdings" || holdings=""' in body       # 失敗只清掉路徑、不進 problems


# ---- push 推「驗過的 sha」而不是會變動的 develop ref；rebase 後重新驗證 ----

def _push_with_hook(repo, hook_body, env_extra=None):
    """把 git_net 換成：遇到 push 先執行 hook_body（第 N 次 push 時 $PUSH_N=N），再照常呼叫真正的 git。"""
    body = ('PUSH_N=0; git_net() { if [[ "$1" == push ]]; then PUSH_N=$((PUSH_N+1)); '
            + hook_body + '; fi; command git "$@" >&2; }; push_journal_cli')
    r = _sh(repo, body, env_extra)
    return r.returncode, r.stdout.strip(), r.stderr


def test_push_sends_validated_sha_not_human_commit_landing_before_push(repo):
    # 驗證通過之後、push 之前，主 checkout 有人疊上非 journal 的 commit：只能推驗過的那個 journal commit
    _journal_commit(repo)
    journal_sha = _git(repo, "rev-parse", "HEAD")
    hook = ('if (( PUSH_N == 1 )); then echo "human work" > other.txt; '
            'git commit -q -am "human: race" >/dev/null; fi')
    rc, out, err = _push_with_hook(repo, hook)
    assert (rc, out) == (0, "push ok"), err
    assert _origin_head(repo) == journal_sha
    assert _git(repo, "log", "-1", "--format=%s") == "human: race"      # 人的 commit 還在本地、沒被推


def test_push_does_not_clobber_origin_when_tracking_ref_is_fresh_but_head_diverged(repo, tmp_path):
    # origin/develop 已 fetch 到別處推的新 commit，本地 journal commit 卻疊在舊 base 上：
    # lease 會放行非 fast-forward，必須靠祖先檢查改走 rebase，不能把別人的 commit 蓋掉
    _advance_origin(tmp_path, repo, "journal/ptt-picks.jsonl", '{"theirs": 1}\n')
    _git(repo, "fetch", "-q", "origin")
    _journal_commit(repo)
    theirs = _git(repo, "rev-parse", "origin/develop")

    assert _push_cli(repo)[:2] == (0, "push ok")
    _git(repo, "fetch", "-q", "origin")
    assert _git(repo, "merge-base", "--is-ancestor", theirs, "origin/develop") == ""
    assert _remote_files(repo) >= {"journal/ptt-picks.jsonl", "journal/media-picks.jsonl"}


def test_push_revalidates_after_rebase_and_refuses_human_commit(repo, tmp_path):
    # 第一次 push 時 origin 被別處推進（lease 擋下），同時本地疊上人的 commit；rebase 後重新驗證必須擋下
    _journal_commit(repo)
    remote = _git(repo, "remote", "get-url", "origin")
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", remote, str(other))
    _git(other, "config", "user.email", "o@example.com")
    _git(other, "config", "user.name", "o")
    hook = (f'if (( PUSH_N == 1 )); then (cd "{other}" && echo x > journal/ptt-picks.jsonl && git add . '
            '&& git commit -q -m theirs && git push -q origin develop) >/dev/null 2>&1; '
            'echo "human work" > other.txt; git commit -q -am "human: race" >/dev/null; fi')
    rc, out, _ = _push_with_hook(repo, hook)
    assert (rc, out) == (1, "push failed")
    assert _origin_head(repo) == _git(other, "rev-parse", "HEAD")      # origin 停在別處推的那個 commit
    assert not (repo / ".git" / "rebase-merge").exists() and not (repo / ".git" / "rebase-apply").exists()


# ---- 鎖：取鎖與死鎖接管在 flock 底下原子完成 ----

def test_acquire_lock_concurrent_takeover_has_single_owner(tmp_path):
    """死鎖留著時三輪同時啟動，只能有一輪拿到鎖。外部 mkdir 換成成功後停 1 秒的版本，
    放大舊寫法「mkdir 與寫 pid 之間」「rm -rf＋mkdir 接管之間」的空窗（新寫法在 perl 裡做，不受影響）。"""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "mkdir").write_text('#!/bin/sh\n/bin/mkdir "$@" || exit $?\nsleep 1\n', encoding="utf-8")
    (bindir / "mkdir").chmod(0o755)
    dead = subprocess.Popen(["true"])
    dead.wait()
    lock = tmp_path / "logs" / ".job.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(dead.pid))
    prelude = (f'source "{JOB}"; LOG=/dev/null; notify_failure() {{ :; }}; ')
    body = 'acquire_lock logs/.job.lock 媒體點名 10800 1; echo acquired; sleep 6'
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    procs = [subprocess.Popen(["bash", "-c", prelude + body], cwd=tmp_path, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, env=env) for _ in range(3)]
    outs = [p.communicate(timeout=60)[0] for p in procs]
    assert sum("acquired" in o for o in outs) == 1, outs
    assert sum("本次不重複跑" in o for o in outs) == 2, outs
    assert not lock.exists()


def test_acquire_lock_treats_eperm_holder_as_alive(tmp_path):
    # pid 1 一定活著但不是我們的行程（kill -0 回 EPERM）：不能當成死鎖接管
    r, log, notify, lock = _lock_run(tmp_path, 1, age_s=5, keep_log=1)
    assert r.returncode == 0 and "acquired" not in r.stdout
    assert "本次不重複跑" in log.read_text(encoding="utf-8")
    assert (lock / "pid").read_text().strip() == "1"


def test_acquire_lock_reclaims_dead_lock_dir_holding_extra_files(tmp_path):
    # 死鎖目錄裡除了 pid 還有別的檔（舊版或手動留下）：回收要整個刪掉，不能因 rmdir 失敗而整輪不跑
    dead = subprocess.Popen(["true"])
    dead.wait()
    lock = tmp_path / "logs" / ".job.lock"
    lock.mkdir(parents=True)
    (lock / "leftover").write_text("x")
    r, _, notify, lock = _lock_run(tmp_path, dead.pid, age_s=5, keep_log=1)
    assert r.returncode == 0 and "acquired" in r.stdout, r.stderr
    assert not notify.exists()
    assert not lock.exists()
