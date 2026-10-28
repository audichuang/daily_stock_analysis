# -*- coding: utf-8 -*-
"""scripts/daily_report.sh 的逾時與鎖齡行为。

只 source 脚本、绝不直接执行（直接执行会 cd、建 log、跑真正的报告流程）。
每个案例用独一无二的 sleep 参数，事后用 pgrep -f 确认没有残留行程。
"""
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "daily_report.sh"

pytestmark = pytest.mark.skipif(
    subprocess.run(["which", "perl"], capture_output=True).returncode != 0,
    reason="需要 perl",
)


def _run_bash(body: str, env_extra=None, timeout=60):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"\n{body}'],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(SCRIPT.parent.parent),
    )


def _unique_sleep() -> str:
    # 31.xxxxxx：够长不会自己结束，又够独特让 pgrep -f 只抓到本案例
    return f"31.{uuid.uuid4().int % 10**6:06d}"


def _leftovers(token: str) -> str:
    out = subprocess.run(["pgrep", "-f", f"sleep {token}"], capture_output=True, text=True)
    return out.stdout.strip()


def test_script_is_valid_bash():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_sourcing_does_not_run_main(tmp_path):
    # source 时若跑了 main，会 cd 到仓库根并建 logs/daily_report_*.log
    body = f'cd "{tmp_path}"; source "{SCRIPT}"; pwd -P; ls -A; declare -F main'
    r = subprocess.run(["bash", "-c", body], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert r.stdout.split() == [str(tmp_path.resolve()), "main"]
    assert not list(tmp_path.iterdir())


def test_run_with_timeout_kills_whole_process_group():
    tok = _unique_sleep()
    t0 = time.time()
    r = _run_bash(f"run_with_timeout 1 bash -c 'sleep {tok} & sleep {tok}'; echo rc=$?")
    # TERM 就该把整个 group 收掉（约 1 秒）；超过 6 秒代表只杀了直接子行程、靠 10 秒后的 KILL 才收尾
    assert time.time() - t0 < 6
    assert "rc=124" in r.stdout
    assert _leftovers(tok) == ""


def test_run_with_timeout_kills_term_ignoring_children():
    tok = _unique_sleep()
    r = _run_bash(
        f"run_with_timeout 1 bash -c 'trap \"\" TERM; sleep {tok} & sleep {tok}'; echo rc=$?"
    )
    assert "rc=124" in r.stdout
    assert _leftovers(tok) == ""


@pytest.mark.parametrize("code", [0, 3])
def test_run_with_timeout_passes_through_exit_code(code):
    r = _run_bash(f"run_with_timeout 20 bash -c 'exit {code}'; echo rc=$?")
    assert f"rc={code}" in r.stdout


def test_run_step_times_out_bash_function_step(tmp_path):
    tok = _unique_sleep()
    log = tmp_path / "step.log"
    body = f"""
LOG="{log}"
notify_failure() {{ echo "$1" >> "{tmp_path}/notified"; }}
slow_step() {{ sleep {tok} & sleep {tok}; }}
( DAILY_REPORT_STEP_TIMEOUT_SECONDS=1 run_step "慢步驟" slow_step ); echo rc=$?
"""
    t0 = time.time()
    r = _run_bash(body)
    assert time.time() - t0 < 15
    assert "rc=1" in r.stdout
    assert "TIMEOUT: 慢步驟" in log.read_text(encoding="utf-8")
    assert "逾時" in (tmp_path / "notified").read_text(encoding="utf-8")
    assert _leftovers(tok) == ""


def test_run_step_times_out_plain_command(tmp_path):
    tok = _unique_sleep()
    log = tmp_path / "step.log"
    body = f"""
LOG="{log}"
notify_failure() {{ echo "$1" >> "{tmp_path}/notified"; }}
( DAILY_REPORT_STEP_TIMEOUT_SECONDS=1 run_step "慢命令" bash -c 'sleep {tok} & sleep {tok}' ); echo rc=$?
"""
    t0 = time.time()
    r = _run_bash(body)
    assert time.time() - t0 < 15
    assert "rc=1" in r.stdout
    assert "TIMEOUT: 慢命令" in log.read_text(encoding="utf-8")
    assert (tmp_path / "notified").exists()
    assert _leftovers(tok) == ""


@pytest.mark.parametrize("ignore_term", [False, True])
def test_timeout_cleans_registered_cli_sessions_before_unlock(tmp_path, ignore_term):
    cli = tmp_path / "fake_cli.py"
    cli.write_text(
        "import os, signal, subprocess, sys, time\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_term else "")
        + "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        + f"with open({str(tmp_path / 'pids')!r}, 'a') as f: f.write(f'{{os.getpid()}} {{child.pid}}\\n')\n"
        + "time.sleep(60)\n",
        encoding="utf-8",
    )
    # 只替換外部 CLI；真正的 backend 必須以 start_new_session 啟動兩份並行請求。
    driver = f"""
from concurrent.futures import ThreadPoolExecutor
import sys
from types import SimpleNamespace
from src.llm.local_cli_backend import LocalCliGenerationBackend, LocalCliPreset
config = SimpleNamespace(generation_backend_timeout_seconds=60,
                         generation_backend_max_concurrency=2, local_cli_backend_max_concurrency=2)
preset = LocalCliPreset(preset_id='codex_cli', executable=sys.executable,
                        argv=({str(cli)!r},), display_name='Mock CLI')
backend = LocalCliGenerationBackend(config, preset=preset)
with ThreadPoolExecutor(max_workers=2) as pool:
    list(pool.map(lambda _: backend.generate('test', {{}}), range(2)))
"""
    outsider = subprocess.Popen(["sleep", "60"], start_new_session=True)
    lock = tmp_path / "lock"
    lock.mkdir()
    snapshot = tmp_path / "at_unlock"
    try:
        r = _run_bash(f"""
LOG="{tmp_path / 'step.log'}"
notify_failure() {{ :; }}
trap 'ps -eo pid=,pgid=,stat= > "{snapshot}"; rmdir "{lock}"' EXIT
DAILY_REPORT_STEP_TIMEOUT_SECONDS=4 run_step "CLI 步驟" {shlex.quote(sys.executable)} -c {shlex.quote(driver)}
""")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "TIMEOUT: CLI 步驟" in (tmp_path / "step.log").read_text()
        groups = [int(line.split()[0]) for line in (tmp_path / "pids").read_text().splitlines()]
        assert len(groups) == 2, "逾時前必須真的啟動兩份 CLI"
        assert not lock.exists()
        for line in snapshot.read_text().splitlines():
            _, pgid, state = line.split()
            assert int(pgid) not in groups or state.startswith("Z"), line
        assert outsider.poll() is None, "不得終止其他步驟／使用者的 session"
    finally:
        outsider.kill()
        outsider.wait()
        # mutation 故意漏殺時也要收乾淨，不能讓測試留下 CLI。
        if (tmp_path / "pids").exists():
            for line in (tmp_path / "pids").read_text().splitlines():
                try:
                    os.killpg(int(line.split()[0]), signal.SIGKILL)
                except ProcessLookupError:
                    pass


def test_run_step_function_returning_nonzero_is_failure(tmp_path):
    log = tmp_path / "step.log"
    body = f"""
LOG="{log}"
notify_failure() {{ echo "$1" >> "{tmp_path}/notified"; }}
bad_step() {{ return 1; }}
( run_step "壞步驟" bad_step ); echo rc=$?
"""
    r = _run_bash(body)
    text = log.read_text(encoding="utf-8")
    assert "rc=1" in r.stdout
    assert "FAILED: 壞步驟" in text
    assert "TIMEOUT" not in text
    assert (tmp_path / "notified").exists()


def test_run_step_function_can_use_say_and_log_var(tmp_path):
    log = tmp_path / "step.log"
    body = f"""
LOG="{log}"
notify_failure() {{ echo "$1" >> "{tmp_path}/notified"; }}
talk_step() {{ say "函式內說話"; echo "LOG=$LOG"; }}
run_step "說話步驟" talk_step; echo rc=$?
"""
    r = _run_bash(body)
    text = log.read_text(encoding="utf-8")
    assert "rc=0" in r.stdout
    assert "函式內說話" in text
    assert f"LOG={log}" in text
    assert not (tmp_path / "notified").exists()


def test_run_step_plain_command_exit_code(tmp_path):
    log = tmp_path / "step.log"
    body = f"""
LOG="{log}"
notify_failure() {{ echo "$1" >> "{tmp_path}/notified"; }}
run_step "好命令" bash -c 'echo hello'; echo ok=$?
( run_step "壞命令" bash -c 'exit 5' ); echo bad=$?
"""
    r = _run_bash(body)
    text = log.read_text(encoding="utf-8")
    assert "ok=0" in r.stdout and "bad=1" in r.stdout
    assert "hello" in text
    assert "FAILED: 壞命令" in text


def _make_lock(tmp_path, age_seconds):
    lock = tmp_path / "lock"
    lock.mkdir()
    ts = time.time() - age_seconds
    os.utime(lock, (ts, ts))
    return lock


def test_lock_age_seconds_is_plain_integer(tmp_path):
    lock = _make_lock(tmp_path, 7200)
    r = _run_bash(f'lock_age_seconds "{lock}"')
    assert re.fullmatch(r"[0-9]+", r.stdout), repr(r.stdout)
    assert 7195 <= int(r.stdout) <= 7260


def test_lock_staleness_threshold(tmp_path):
    old = _make_lock(tmp_path, 4 * 3600)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    r = _run_bash(
        f'lock_is_stale "{old}" && echo old=stale || echo old=ok\n'
        f'lock_is_stale "{fresh}" && echo fresh=stale || echo fresh=ok'
    )
    assert "old=stale" in r.stdout
    assert "fresh=ok" in r.stdout
    # 门槛可由变数覆写：调大后同一把旧锁不再算 stale
    r = _run_bash(
        f'lock_is_stale "{old}" && echo old=stale || echo old=ok',
        env_extra={"DAILY_REPORT_STALE_LOCK_SECONDS": str(10 * 3600)},
    )
    assert "old=ok" in r.stdout


def _sandbox(tmp_path):
    """在 tmp 里放一份脚本副本 + 假的 uv／doppler，直接执行 main（不碰真实仓库与 Telegram）。"""
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "daily_report.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "doppler_calls"
    # 假 uv：问 expected_session 时回 $FAKE_EXPECTED（未设＝空），其余步骤一律成功；
    # 假 doppler：主分析步骤（带 finmind）印出个股汇总行，其余只记呼叫。
    (bindir / "uv").write_text(
        f"#!/bin/sh\ncase \"$*\" in *expected_session*) echo \"${{FAKE_EXPECTED:-}}\";; "
        f"*notify.py*) {{ printf '%s\\n' \"$*\"; cat; echo; }} >> \"{tmp_path}/notify_args\";; *) echo '{{}}';; esac\n"
    )
    (bindir / "doppler").write_text(
        f'#!/bin/sh\necho "$@" >> "{calls}"\n'
        'case "$*" in *notify.py*) while [ "$1" != "--" ]; do shift; done; shift; exec "$@";; esac\n'
        'case "$*" in *finmind*) if [ -n "$FAKE_FAIL" ]; then '
        'echo "[5469.TW] 分析未成功: x"; echo "成功: 2, 失败: 1"; else echo "成功: 1, 失败: 0"; fi;; esac\n'
    )
    for f in bindir.iterdir():
        f.chmod(0o755)
    return script, bindir, calls


def _run_main_with_lock(tmp_path, lock_age):
    script, bindir, calls = _sandbox(tmp_path)
    holder = subprocess.Popen(["sleep", _unique_sleep()])
    try:
        lock = tmp_path / "logs" / ".daily_report.lock"
        lock.mkdir(parents=True)
        (lock / "pid").write_text(str(holder.pid))
        ts = time.time() - lock_age
        os.utime(lock, (ts, ts))
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
        r = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True, timeout=60, env=env, cwd=str(tmp_path)
        )
    finally:
        holder.kill()
        holder.wait()
    return r, tmp_path / "logs", calls


def test_main_alerts_when_live_lock_holder_is_stuck(tmp_path):
    r, logs, calls = _run_main_with_lock(tmp_path, 4 * 3600)
    assert r.returncode == 1
    assert calls.exists(), "卡住的锁必须推通知"
    assert list(logs.glob("daily_report_*.log")), "要保留本轮 log"
    assert "已卡住" in r.stdout


def test_main_skips_quietly_when_live_lock_is_recent(tmp_path):
    r, logs, calls = _run_main_with_lock(tmp_path, 60)
    assert r.returncode == 0
    assert not calls.exists()
    assert not list(logs.glob("daily_report_*.log"))
    assert "本次不重複跑" in r.stdout


# ---- 完成标记：「<曆日>|<expected_session>」 ----

TODAY = "20261016"


@pytest.mark.parametrize(
    "mark, key, skipped",
    [
        # 同日同场次 → 跳过
        (f"{TODAY}|2026-10-16", f"{TODAY}|2026-10-16", True),
        # 盘中手动跑留下的标记（场次=前一交易日）不挡 18:00（场次=今天）
        (f"{TODAY}|2026-10-15", f"{TODAY}|2026-10-16", False),
        # 台股休市日（10-09：场次仍是 10-08、美股开市）：前一晚的标记不挡隔天
        ("20261008|2026-10-08", "20261009|2026-10-08", False),
        # 同一天、场次也没变（盘中重跑）→ 跳过
        (f"{TODAY}|2026-10-15", f"{TODAY}|2026-10-15", True),
        # 日历不可用：KEY 空 → 永不跳过
        (f"{TODAY}|2026-10-16", "", False),
        # 只剩曆日（没有场次）的 KEY 不是合法键，不得当成「相等」而跳过
        (f"{TODAY}|", f"{TODAY}|", False),
        # MARK 空档
        ("", f"{TODAY}|2026-10-16", False),
    ],
)
def test_session_already_reported_truth_table(tmp_path, mark, key, skipped):
    mark_file = tmp_path / "mark"
    mark_file.write_text(mark + ("\n" if mark else ""), encoding="utf-8")
    r = _run_bash(f'session_already_reported "{mark_file}" "{key}" && echo skip || echo run')
    assert r.stdout.strip() == ("skip" if skipped else "run")


def test_session_already_reported_missing_mark_runs(tmp_path):
    r = _run_bash(f'session_already_reported "{tmp_path}/nope" "{TODAY}|2026-10-16" && echo skip || echo run')
    assert r.stdout.strip() == "run"


def test_session_key_assembly():
    from datetime import datetime

    today = datetime.now().strftime("%Y%m%d")
    r = _run_bash('session_key "2026-10-16"; echo; session_key ""; echo; session_key "garbage"; echo')
    assert r.stdout.split("\n")[:3] == [f"{today}|2026-10-16", "", ""]


LOG_1016 = """\
2026-10-16 18:18:09 | WARNING  | src.core.pipeline | src/core/pipeline.py:3399 | [3481.TW] 分析未成功: approval_required at execution for backend claude_code_cli
2026-10-16 18:18:27 | WARNING  | src.core.pipeline | src/core/pipeline.py:3399 | [5469.TW] 分析未成功: approval_required at execution for backend claude_code_cli
2026-10-16 18:18:31 | WARNING  | src.core.pipeline | src/core/pipeline.py:3399 | [6191.TW] 分析未成功: approval_required at execution for backend claude_code_cli
2026-10-16 18:18:31 | WARNING  | src.core.pipeline | src/core/pipeline.py:3399 | [6191.TW] 分析未成功: 重試後仍失敗
2026-10-16 18:18:31 | INFO     | src.core.pipeline | src/core/pipeline.py:3625 | 成功: 33, 失败: 3, 耗时: 996.30 秒
"""


def test_failed_codes_dedupes_and_sorts(tmp_path):
    log = tmp_path / "x.log"
    log.write_text(LOG_1016 + "[00631L.TW] 分析未成功: x\n", encoding="utf-8")
    r = _run_bash(f'failed_codes "{log}" | tr "\\n" " "')
    assert r.stdout.strip() == "00631L.TW 3481.TW 5469.TW 6191.TW"


def _partial_failure_body(tmp_path, summary_line):
    log = tmp_path / "x.log"
    log.write_text(LOG_1016.replace("成功: 33, 失败: 3", summary_line), encoding="utf-8")
    return f"""
LOG="{log}"
notify_failure() {{ printf '%s\\t%s\\n' "${{2:-}}" "$1" >> "{tmp_path}/notified"; }}
require_stock_success; echo rc=$?
"""


def test_require_stock_success_partial_failure_pushes_nonfatal_notice(tmp_path):
    r = _run_bash(_partial_failure_body(tmp_path, "成功: 33, 失败: 3"))
    assert "rc=0" in r.stdout
    title, body = (tmp_path / "notified").read_text(encoding="utf-8").strip().split("\t", 1)
    assert title == "每日報告部分失敗"
    for code in ("3481.TW", "5469.TW", "6191.TW"):
        assert code in body


def test_require_stock_success_no_failure_no_notice(tmp_path):
    r = _run_bash(_partial_failure_body(tmp_path, "成功: 36, 失败: 0"))
    assert "rc=0" in r.stdout
    assert not (tmp_path / "notified").exists()


def test_require_stock_success_all_failed_is_fatal_without_duplicate_notice(tmp_path):
    # 全败由 run_step 推致命通知；这里不再多推一则「部分失敗」
    r = _run_bash(_partial_failure_body(tmp_path, "成功: 0, 失败: 3"))
    assert "rc=1" in r.stdout
    assert not (tmp_path / "notified").exists()


def test_notify_failure_title_topic_defaults_and_overrides(tmp_path):
    # 假 doppler 執行 `--` 之後的命令；假 uv 記下 argv 與 stdin（內文走 stdin，不進 argv）
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "uv").write_text(f'#!/bin/sh\n{{ printf "%s|" "$@"; printf "STDIN=%s" "$(cat)"; echo; }} >> "{tmp_path}/uv_args"\n')
    (bindir / "doppler").write_text('#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done; shift; exec "$@"\n')
    for f in bindir.iterdir():
        f.chmod(0o755)
    env = {"PATH": f"{bindir}:{os.environ['PATH']}"}
    _run_bash('notify_failure "內文"; notify_failure "內文2" "自訂標題"; notify_failure "內文3" "回驗" morning',
              env_extra=env)
    lines = (tmp_path / "uv_args").read_text(encoding="utf-8").strip().split("\n")
    assert lines[0] == "run|python|scripts/notify.py|--topic|system|--title|每日報告失敗|STDIN=內文"
    assert lines[1] == "run|python|scripts/notify.py|--topic|system|--title|自訂標題|STDIN=內文2"
    assert lines[2] == "run|python|scripts/notify.py|--topic|morning|--title|回驗|STDIN=內文3"


def _notify_bin(tmp_path, uv_body):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "uv").write_text(f"#!/bin/sh\n{uv_body}\n")
    (bindir / "doppler").write_text('#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done; shift; exec "$@"\n')
    for f in bindir.iterdir():
        f.chmod(0o755)
    return {"PATH": f"{bindir}:{os.environ['PATH']}"}


def test_notify_failure_output_and_reason_go_to_log(tmp_path):
    # notify.py 未送出的原因（stderr）要留在 log，失敗要記 WARN；不能被丟進 /dev/null
    env = _notify_bin(tmp_path, 'echo "[notify] 未注入 TELEGRAM_TOPIC_SYSTEM，不送" >&2; exit 1')
    log = tmp_path / "run.log"
    _run_bash(f'LOG="{log}"; notify_failure "內文"', env_extra=env)
    text = log.read_text(encoding="utf-8")
    assert "未注入 TELEGRAM_TOPIC_SYSTEM" in text and "WARN: Telegram 通知也没送出去" in text


def test_notify_failure_is_bounded_by_timeout(tmp_path):
    # 通知卡住（HTTP 一直不結束）不能拖住腳本與鎖：整次呼叫有上限、逾時記 WARN
    marker = _unique_sleep()
    env = _notify_bin(tmp_path, f"cat >/dev/null; exec sleep {marker}")
    env["NOTIFY_TIMEOUT_SECONDS"] = "1"
    log = tmp_path / "run.log"
    start = time.monotonic()
    _run_bash(f'LOG="{log}"; notify_failure "內文"', env_extra=env, timeout=30)
    assert time.monotonic() - start < 15
    assert "WARN: Telegram 通知也没送出去" in log.read_text(encoding="utf-8")
    assert subprocess.run(["pgrep", "-f", f"sleep {marker}"], capture_output=True).returncode != 0


def _run_main_sandbox(tmp_path, *, mark, expected, force=False):
    script, bindir, calls = _sandbox(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    if mark is not None:
        (logs / ".daily_report_last_session").write_text(mark + "\n", encoding="utf-8")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_EXPECTED=expected)
    env.pop("DAILY_REPORT_FORCE", None)
    if force:
        env["DAILY_REPORT_FORCE"] = "1"
    r = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, timeout=60, env=env, cwd=str(tmp_path)
    )
    return r, logs


def _today():
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d")


def test_main_skips_same_day_same_session(tmp_path):
    r, logs = _run_main_sandbox(tmp_path, mark=f"{_today()}|2026-10-16", expected="2026-10-16")
    assert r.returncode == 0
    assert "本交易場次已產出過報告" in r.stdout
    assert not list(logs.glob("daily_report_*.log"))


def test_main_midday_mark_does_not_block_evening_run_and_updates_mark(tmp_path):
    r, logs = _run_main_sandbox(tmp_path, mark=f"{_today()}|2026-10-15", expected="2026-10-16")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "本交易場次已產出過報告" not in r.stdout
    assert "daily report done" in r.stdout
    assert (logs / ".daily_report_last_session").read_text(encoding="utf-8").strip() == f"{_today()}|2026-10-16"


def test_main_force_overrides_mark(tmp_path):
    r, logs = _run_main_sandbox(tmp_path, mark=f"{_today()}|2026-10-16", expected="2026-10-16", force=True)
    assert "本交易場次已產出過報告" not in r.stdout
    assert "daily report done" in r.stdout


def test_main_without_calendar_never_skips_and_writes_no_mark(tmp_path):
    r, logs = _run_main_sandbox(tmp_path, mark=f"{_today()}|2026-10-16", expected="")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "daily report done" in r.stdout
    # 既有标记原封不动（没有拿空场次覆写）
    assert (logs / ".daily_report_last_session").read_text(encoding="utf-8").strip() == f"{_today()}|2026-10-16"
    assert "取不到交易日曆" in r.stdout


def test_main_without_calendar_and_no_mark_creates_none(tmp_path):
    r, logs = _run_main_sandbox(tmp_path, mark=None, expected="")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (logs / ".daily_report_last_session").exists()


def test_main_partial_failure_pushes_titled_notice_through_run_step(tmp_path, monkeypatch):
    # 走完整 run_step（函式被 export -f 交给子 bash）：部分失败通知要真的送得出去，且整轮仍成功
    monkeypatch.setenv("FAKE_FAIL", "1")
    r, logs = _run_main_sandbox(tmp_path, mark=None, expected="2026-10-16")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "daily report done" in r.stdout
    sent = (tmp_path / "notify_args").read_text(encoding="utf-8")
    assert "每日報告部分失敗" in sent and "5469.TW" in sent
    assert (logs / ".daily_report_last_session").exists()


# ---------- 盤前判讀回驗（morning_call_outcomes）：非致命、只 commit outcomes 檔 ----------

def _outcomes_repo(tmp_path, uv_body, branch="develop"):
    """暫存 git repo＋假 uv（印回驗輸出）＋假 media_picks_job.sh（印 push 結果）。"""
    repo = tmp_path / "repo"
    (repo / "journal").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "journal" / "morning-calls-outcomes.jsonl").write_text('{"date": "2099-03-03"}\n', encoding="utf-8")
    (repo / "other.txt").write_text("x\n", encoding="utf-8")
    (repo / "scripts" / "media_picks_job.sh").write_text('echo "push ok"\n', encoding="utf-8")
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["init", "-q", "-b", branch], check=True)
    subprocess.run(git + ["-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], check=True)
    subprocess.run(git + ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], check=True)
    (repo / "other.txt").write_text("staged change\n", encoding="utf-8")
    subprocess.run(git + ["add", "other.txt"], check=True)   # index 裡有別的暫存：不能被帶進 commit
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "uv").write_text(f"#!/usr/bin/env bash\n{uv_body}\n", encoding="utf-8")
    (bindir / "uv").chmod(0o755)
    return repo, bindir


def _run_outcomes(repo, bindir):
    log = repo / "run.log"
    body = (f'cd "{repo}"; LOG="{log}"\n'
            'notify_failure() { printf "NOTIFY %s|%s|topic=%s\\n" "$2" "$1" "${3:-system}" >>"$LOG"; }\n'
            'morning_call_outcomes; echo "rc=$?"')
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    r = _run_bash(body, env_extra=env)
    return r, log.read_text(encoding="utf-8") if log.exists() else ""


def _last_commit_files(repo):
    out = subprocess.run(["git", "-C", str(repo), "show", "--name-only", "--format=%s", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return out[0], [f for f in out[1:] if f]


def test_morning_outcomes_commits_only_outcomes_file_and_notifies(tmp_path):
    repo, bindir = _outcomes_repo(
        tmp_path, 'echo \'{"date": "2099-03-04"}\' >> journal/morning-calls-outcomes.jsonl; echo "PUSH: 2099-03-04 摘要"')
    r, log = _run_outcomes(repo, bindir)
    assert "rc=0" in r.stdout
    subject, files = _last_commit_files(repo)
    assert subject.startswith("journal: morning call outcomes")
    assert files == ["journal/morning-calls-outcomes.jsonl"]
    assert "NOTIFY 盤前判讀回驗" in log and "2099-03-04 摘要" in log and "push ok" in log
    assert "push ok）|topic=morning" in log


def test_morning_outcomes_failure_is_not_fatal_and_commits_nothing(tmp_path):
    repo, bindir = _outcomes_repo(tmp_path, 'echo boom; exit 3')
    r, log = _run_outcomes(repo, bindir)
    assert "rc=0" in r.stdout                       # 回驗壞掉不能讓每日報告 exit
    assert _last_commit_files(repo)[0] == "init"
    assert "WARN: 盤前判讀回驗失敗（rc=3）" in log and "NOTIFY 盤前判讀回驗失敗" in log


def test_morning_outcomes_without_new_rows_is_silent(tmp_path):
    repo, bindir = _outcomes_repo(tmp_path, 'echo "寫入 0 筆"')
    r, log = _run_outcomes(repo, bindir)
    assert "rc=0" in r.stdout and "NOTIFY" not in log
    assert _last_commit_files(repo)[0] == "init"


def test_morning_outcomes_off_develop_does_not_commit(tmp_path):
    repo, bindir = _outcomes_repo(
        tmp_path, 'echo \'{"date": "2099-03-04"}\' >> journal/morning-calls-outcomes.jsonl; echo "PUSH: x"',
        branch="feat/x")
    r, log = _run_outcomes(repo, bindir)
    assert "rc=0" in r.stdout
    assert _last_commit_files(repo)[0] == "init"
    assert "未 commit（主 checkout 在 feat/x）" in log


def test_morning_outcomes_retries_a_failed_commit_on_the_next_run(tmp_path):
    repo, bindir = _outcomes_repo(
        tmp_path, 'echo \'{"date": "2099-03-04"}\' >> journal/morning-calls-outcomes.jsonl; echo "PUSH: x"')
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    _, log = _run_outcomes(repo, bindir)
    assert "commit 失敗" in log and _last_commit_files(repo)[0] == "init"
    hook.unlink()
    (bindir / "uv").write_text('#!/usr/bin/env bash\necho "寫入 0 筆"\n', encoding="utf-8")   # 這一輪沒有新結果
    r, log = _run_outcomes(repo, bindir)
    assert "rc=0" in r.stdout
    subject, files = _last_commit_files(repo)
    assert subject.startswith("journal: morning call outcomes") and files == ["journal/morning-calls-outcomes.jsonl"]
    assert "push ok" in log
