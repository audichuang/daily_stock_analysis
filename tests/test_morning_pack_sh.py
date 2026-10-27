"""scripts/morning_pack.sh：成功才發布 pack、結束碼永遠是指令自己的、儲存失敗只 WARN。"""
import datetime as dt
import importlib.util
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "morning_pack.sh"
_spec = importlib.util.spec_from_file_location("morning_fable_arms", ROOT / "scripts" / "morning_fable_arms.py")
mfa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mfa)


def pack(directory, *cmd):
    p = subprocess.run(["bash", str(SCRIPT), str(directory), *cmd], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def today():
    return (dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))).date().isoformat()


def test_success_publishes_pack_and_streams_stdout(tmp_path):
    rc, out, _ = pack(tmp_path / "packs", "sh", "-c", "echo hello; echo bye")
    assert rc == 0 and out == "hello\nbye\n"
    files = sorted(p.name for p in (tmp_path / "packs").iterdir())
    assert files == [f"{today()}.txt"]
    assert (tmp_path / "packs" / files[0]).read_text() == "hello\nbye\n"


def test_failed_command_keeps_its_exit_code_and_leaves_no_pack(tmp_path):
    rc, out, _ = pack(tmp_path / "packs", "sh", "-c", "echo partial; exit 3")
    assert rc == 3 and out == "partial\n"
    assert list((tmp_path / "packs").iterdir()) == []


def test_unwritable_target_never_changes_exit_code(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")                       # mkdir 會失敗
    rc, out, err = pack(blocker / "packs", "sh", "-c", "echo hi")
    assert (rc, out) == (0, "hi\n") and "WARN" in err
    assert pack(blocker / "packs", "sh", "-c", "exit 4")[0] == 4
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)         # mkdir 成功、tee 開不了檔
    try:
        if os.access(ro, os.W_OK):
            pytest.skip("目錄仍可寫（root？）")
        rc, out, err = pack(ro, "sh", "-c", "echo hi")
        assert (rc, out) == (0, "hi\n") and "WARN" in err
        assert pack(ro, "sh", "-c", "exit 5")[0] == 5
    finally:
        ro.chmod(stat.S_IRWXU)


def test_second_success_same_day_gets_seconds_name_and_find_pack_keeps_first(tmp_path):
    d = tmp_path / "packs"
    pack(d, "sh", "-c", "echo first")
    pack(d, "sh", "-c", "echo second")
    names = sorted(p.name for p in d.iterdir())
    assert len(names) == 2 and f"{today()}.txt" in names
    other = next(n for n in names if n != f"{today()}.txt")
    assert len(other.split(".")) == 3 and len(other.split(".")[1]) == 6    # <date>.<HHMMSS>.txt
    assert mfa.find_pack(today(), d).read_text() == "first\n"


def test_failed_rerun_does_not_touch_existing_pack(tmp_path):
    d = tmp_path / "packs"
    pack(d, "sh", "-c", "echo first")
    pack(d, "sh", "-c", "echo broken; exit 1")
    assert [p.name for p in d.iterdir()] == [f"{today()}.txt"]
    assert (d / f"{today()}.txt").read_text() == "first\n"


@pytest.mark.parametrize("rc_cmd, expected_rc", [("", 0), ("; exit 7", 7)])
def test_tee_failure_midway_never_publishes_truncated_pack(tmp_path, rc_cmd, expected_rc):
    """tee 寫到一半失敗（檔案大小上限＝磁碟滿的替身）：不發布截斷檔、印 WARN，結束碼仍是指令自己的。"""
    d = tmp_path / "packs"
    producer = f"head -c 65536 /dev/zero | tr '\\0' a{rc_cmd}"
    # ulimit -f 單位依 shell 模式是 512 或 1024 bytes，4 個單位至多 4KB，遠小於 64KB
    script = f"ulimit -f 4; trap '' XFSZ; exec bash {SCRIPT} {d} sh -c \"{producer}\""
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert p.returncode == expected_rc
    assert "WARN" in p.stderr and len(p.stdout) == 65536     # 終端那份是完整的
    assert list(d.iterdir()) == []
