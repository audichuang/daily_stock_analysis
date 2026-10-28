#!/usr/bin/env python3
"""沿用每日報告的私有 CLI PGID 登記格式，清理本輪獨立 session。"""

import fcntl
import os
from pathlib import Path
import signal
import stat
import subprocess
import time


REGISTRY_NAME = "local-cli.registry"


def prepare(run):
    """建立 0600 的 open 登記檔，供 _DSA_LOCAL_CLI_REGISTRY 指向。"""
    path = Path(run).resolve() / REGISTRY_NAME
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as registry:
        registry.write("open\n")
    return path


def _members(groups):
    output = subprocess.check_output(
        ["ps", "-axo", "pid=,pgid=,stat="], text=True,
    )
    members = {group: [] for group in groups}
    for line in output.splitlines():
        pid, group, state = line.split(maxsplit=2)
        group = int(group)
        if group in members:
            members[group].append({"pid": int(pid), "state": state})
    return members


def _running(groups):
    # 殭屍已停止執行，由原父程序回收；訊號無法再終止它。
    return {
        group: members for group, members in _members(groups).items()
        if any(not member["state"].startswith("Z") for member in members)
    }


def _signal_groups(groups, sig):
    signalled = []
    for group in groups:
        try:
            os.killpg(group, sig)
            signalled.append(group)
        except ProcessLookupError:
            pass
    return signalled


def cleanup_registry(run):
    """先以同一把 flock 封閉登記，再清理已登記 PGID；回傳證據。"""
    path = Path(run).resolve() / REGISTRY_NAME
    if not path.exists():
        return {"registered": False, "success": True, "reason": "registry_not_created"}
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "r+", encoding="ascii") as registry:
        metadata = os.fstat(registry.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600):
            raise RuntimeError("CLI 登記檔必須是本使用者所有、權限 0600 的一般檔案")
        fcntl.flock(registry, fcntl.LOCK_EX)
        lines = registry.read().splitlines()
        if not lines or lines[0] not in {"open", "closed"}:
            raise RuntimeError("CLI 登記檔缺少既有 open/closed 標頭")
        entries = [line.strip() for line in lines[1:] if line.strip()]
        if any(not value.isascii() or not value.isdigit() for value in entries):
            raise RuntimeError("CLI 登記檔含非數字 PGID，保留現場")
        groups = list(dict.fromkeys(int(value) for value in entries))
        if any(group <= 1 or group == os.getpgrp() for group in groups):
            raise RuntimeError("CLI 登記檔指到受保護程序群組，拒絕送訊號")
        # 生產端在同把鎖內 spawn＋登記；closed 後不會再新增 CLI。
        registry.seek(0)
        registry.write("closed\n" + "".join(f"{group}\n" for group in groups))
        registry.truncate()
        registry.flush()
        before = _members(groups)
        for group in groups:
            try:
                actual = os.getpgid(group)
            except ProcessLookupError:
                # 領頭程序已退出時，登記的群組仍可能留有子程序。
                continue
            if actual != group:
                raise RuntimeError(f"登記 PID {group} 已不是同號 PGID，保留現場")
        term = _signal_groups(groups, signal.SIGTERM)
        fcntl.flock(registry, fcntl.LOCK_UN)
        deadline = time.monotonic() + 10
        remaining = _running(groups)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.2)
            remaining = _running(groups)
        killed = _signal_groups(remaining, signal.SIGKILL)
        deadline = time.monotonic() + 2
        remaining = _running(groups)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.1)
            remaining = _running(groups)
        if not remaining:
            fcntl.flock(registry, fcntl.LOCK_EX)
            registry.seek(0)
            registry.write("closed\n")
            registry.truncate()
            registry.flush()
        return {
            "registered": True, "success": not remaining, "registry": str(path),
            "groups": groups, "before": before, "term_sent": term, "kill_sent": killed,
            "remaining": remaining, "after": _members(groups),
        }
