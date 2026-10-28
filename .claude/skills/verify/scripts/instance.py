#!/usr/bin/env python3
"""啟動、檢查、清理本次驗證專用的真實 Web/API。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[4]
SOURCE_DIRS = {"api", "src", "data_provider", "bot", "market_data", "strategies", "templates"}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def request(meta, route):
    with urlopen(meta["url"] + route, timeout=5) as response:
        return json.load(response)


def owned(meta):
    result = subprocess.run(
        ["ps", "-p", str(meta["pid"]), "-o", "command="], capture_output=True, text=True,
    )
    return result.returncode == 0 and meta["bootstrap"] in result.stdout


def launch(run, space_id):
    run.mkdir(parents=True, exist_ok=False)
    save(run / "launch.json", {"run_dir": str(run), "created_by": "dsa-verify"})
    runtime = run / "runtime"
    source = runtime / "source"
    source.mkdir(parents=True)
    # 複製當前已追蹤原始碼（含未提交修改），排除 .env 與執行期資料。
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    hashes = {}
    for name in filter(None, paths):
        relative = Path(name)
        if (relative.parts[0] not in SOURCE_DIRS
                and name != "apps/dsa-web/public/stocks.index.json"
                and not (len(relative.parts) == 1 and relative.suffix == ".py")):
            continue
        original = ROOT / relative
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
        hashes[name] = hashlib.sha256(original.read_bytes()).hexdigest()
    save(run / "source-hashes.json", hashes)
    env_path = runtime / "verification.env"
    settings = {
        "ENV_FILE": str(env_path), "DATABASE_PATH": str(runtime / "state" / "application.db"),
        "STORAGE_DATABASE_URL": "", "DATABASE_URL": "", "LITELLM_MODE": "PRODUCTION",
        "ADMIN_AUTH_ENABLED": "false", "SCHEDULE_ENABLED": "false",
        "SCHEDULE_RUN_IMMEDIATELY": "false", "DSA_RUNTIME_SCHEDULER_SUPPRESS_START": "true",
        "AGENT_EVENT_MONITOR_ENABLED": "false", "STOCK_INDEX_REMOTE_UPDATE_ENABLED": "false",
        "PORTFOLIO_FX_UPDATE_ENABLED": "false", "WEBUI_AUTO_BUILD": "false",
        "LOG_DIR": str(runtime / "logs"), "PYTHONPATH": str(source),
    }
    env_path.write_text("".join(f"{key}={value}\n" for key, value in settings.items()), encoding="utf-8")
    save(run / "isolation.json", settings)
    build_env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "HOME") if key in os.environ}
    # Vite 優先使用程序環境，明確清空以覆蓋 .env*，固定使用同源 API。
    build_env["VITE_API_URL"] = ""
    save(run / "build-isolation.json", {"VITE_API_URL": "", "environment_keys": sorted(build_env)})
    with (run / "build.log").open("w") as output:
        command = ["npm", "run", "build", "--", "--outDir", str(runtime / "web")]
        save(run / "build-command.json", command)
        result = subprocess.run(command, cwd=ROOT / "apps/dsa-web", env=build_env,
                                stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        cleanup(run)
        raise RuntimeError(f"前端建置失敗，見 {run / 'build.log'}；尚未啟動程序")
    build = json.loads((runtime / "web/build-info.json").read_text())
    save(run / "build-info.json", build)
    # 在此綁定 loopback socket 再交給 uvicorn，不使用固定共用 port。
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    bootstrap = runtime / "serve.py"
    bootstrap.write_text(
        "import json\nfrom pathlib import Path\nimport uvicorn\n"
        "from src.config import get_config\nfrom src.storage import DatabaseManager\n"
        "from api.app import create_app\n"
        "if __name__ == '__main__':\n"
        "    config = get_config()\n    DatabaseManager()\n"
        f"    Path({str(run / 'effective-storage.json')!r}).write_text(json.dumps("
        "{'db_url': config.get_db_url(), 'schedule_enabled': config.schedule_enabled}, indent=2))\n"
        f"    uvicorn.run(create_app(Path({str(runtime / 'web')!r})), fd={listener.fileno()}, log_level='info')\n",
        encoding="utf-8",
    )
    child_env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
    child_env.update(settings)
    child_env["HOME"] = str(runtime / "home")
    Path(child_env["HOME"]).mkdir()
    with (run / "server.log").open("w") as output:
        process = subprocess.Popen(
            [sys.executable, "-u", str(bootstrap)], cwd=source, env=child_env,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
            pass_fds=(listener.fileno(),),
        )
    listener.close()
    meta = {
        "run_dir": str(run), "pid": process.pid, "bootstrap": str(bootstrap),
        "url": f"http://127.0.0.1:{port}", "port": port, "head": git("rev-parse", "HEAD"),
        "remote_baseline": git("rev-parse", "origin/develop"),
        "worktree_status": git("status", "--short"), "build": build,
        "browser_space_id": space_id, "account_name": f"VERIFY-{run.name}"[:64],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    save(run / "instance.json", meta)
    entry = (
        f"const {{ verifyPortfolio }} = await import({(ROOT / '.claude/skills/verify/scripts/portfolio.mjs').as_uri()!r});\n"
        f"await verifyPortfolio({str(run)!r});\n"
    )
    (run / "drive-portfolio.mjs").write_text(entry, encoding="utf-8")
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"API 提前退出，見 {run / 'server.log'}")
            try:
                if request(meta, "/health")["status"] == "ok":
                    # Launch 初始化可用的空 schema，唯讀 Doctor 不負責首次建表。
                    accounts = request(meta, "/api/v1/portfolio/accounts")
                    assert accounts["accounts"] == [], accounts
                    save(run / "initial-accounts.json", accounts)
                    print(json.dumps(meta, ensure_ascii=False, indent=2))
                    return
            except OSError:
                time.sleep(0.25)
        raise RuntimeError("API 未在 45 秒內就緒")
    except BaseException:
        cleanup(run)
        raise


def doctor(run):
    meta = json.loads((run / "instance.json").read_text())
    assert owned(meta), "PID 不屬於本次 bootstrap，拒絕操作"
    listener = subprocess.check_output(
        ["lsof", "-nP", "-a", "-p", str(meta["pid"]), f"-iTCP:{meta['port']}", "-sTCP:LISTEN"], text=True,
    )
    storage = json.loads((run / "effective-storage.json").read_text())
    assert storage["db_url"] == f"sqlite:///{run / 'runtime/state/application.db'}", storage
    assert storage["schedule_enabled"] is False, storage
    health = request(meta, "/health")
    auth = request(meta, "/api/v1/auth/status")
    build = request(meta, "/build-info.json")
    assert health["status"] == "ok", health
    assert auth["authEnabled"] is False, auth
    assert build == meta["build"], "建置身分不符"
    result = {"url": meta["url"], "head": meta["head"], "listener": listener,
              "storage": storage, "health": health, "auth": auth, "build": build}
    save(run / "doctor.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cleanup(run):
    if not (run / "instance.json").exists():
        marker = json.loads((run / "launch.json").read_text())
        assert marker == {"run_dir": str(run), "created_by": "dsa-verify"}, "不是本次 launcher 建立的目錄"
        if (run / "runtime").exists():
            shutil.rmtree(run / "runtime")
        save(run / "cleanup.json", {"process_started": False, "runtime_removed": True})
        print(f"未啟動程序；已清理 runtime，建置證據保留於 {run}")
        return
    meta = json.loads((run / "instance.json").read_text())
    if owned(meta):
        os.killpg(meta["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 10
        while owned(meta) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not owned(meta), "本次程序尚未退出，保留 runtime 供調查"
    # PID 重用或殘留子程序時保留現場，不能移除仍在使用的 runtime。
    result = subprocess.run(["lsof", "-t", f"-iTCP:{meta['port']}", "-sTCP:LISTEN"], capture_output=True, text=True)
    assert not result.stdout.strip(), "Port 仍有人占用；保留 runtime，先調查擁有者"
    database = run / "runtime/state/application.db"
    if database.exists():
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            with sqlite3.connect(run / "application-evidence.sqlite3") as destination:
                connection.backup(destination)
            connection.row_factory = sqlite3.Row
            save(run / "portfolio-rows.json", {
                table: [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
                for table in ("portfolio_accounts", "portfolio_cash_ledger")
            })
    cache = run / "runtime/source/data/cache/akshare_name_map.json"
    cache_created = cache.exists()
    shutil.rmtree(run / "runtime")
    save(run / "cleanup.json", {"pid": meta["pid"], "process_stopped": not owned(meta),
         "port_released": True, "akshare_cache_created": cache_created, "runtime_removed": True,
         "evidence_files": sorted(path.name for path in run.iterdir() if path.name != "runtime")})
    assert (run / "server.log").is_file() and (run / "cleanup.json").is_file()
    print(f"已清理本次 runtime；證據保留於 {run}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("launch", "doctor", "cleanup"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--space-id", type=int)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    if args.action == "launch":
        launch(run, args.space_id)
    elif args.action == "doctor":
        doctor(run)
    else:
        cleanup(run)


if __name__ == "__main__":
    main()
