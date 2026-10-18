# -*- coding: utf-8 -*-
"""scripts/daily_report.sh 的逾時與鎖齡行为。

只 source 脚本、绝不直接执行（直接执行会 cd、建 log、跑真正的报告流程）。
每个案例用独一无二的 sleep 参数，事后用 pgrep -f 确认没有残留行程。
"""
import os
import re
import subprocess
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
    """在 tmp 里放一份脚本副本 + 假的 uv／doppler，直接执行 main（不碰真实仓库与 Bark）。"""
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "daily_report.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "doppler_calls"
    (bindir / "uv").write_text("#!/bin/sh\necho '{}'\n")
    (bindir / "doppler").write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n')
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
    assert calls.exists(), "卡住的锁必须推 Bark"
    assert list(logs.glob("daily_report_*.log")), "要保留本轮 log"
    assert "已卡住" in r.stdout


def test_main_skips_quietly_when_live_lock_is_recent(tmp_path):
    r, logs, calls = _run_main_with_lock(tmp_path, 60)
    assert r.returncode == 0
    assert not calls.exists()
    assert not list(logs.glob("daily_report_*.log"))
    assert "本次不重複跑" in r.stdout
