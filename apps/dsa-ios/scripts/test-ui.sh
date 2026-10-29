#!/bin/bash
# 真啟動 iOS App 操作合成 HTTP fixture；保留建置、測試、截圖與伺服器日誌。
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "用法：bash scripts/test-ui.sh <simulator-udid> [證據目錄]" >&2
  exit 2
fi
DSA_SIMULATOR_ID="$1"
DSA_IOS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DSA_EVIDENCE_DIR="${2:-$(mktemp -d /tmp/dsa-ios-ui.XXXXXX)}"
mkdir -p "$DSA_EVIDENCE_DIR"
DSA_EVIDENCE_DIR="$(cd "$DSA_EVIDENCE_DIR" && pwd)"
echo "驗收證據：$DSA_EVIDENCE_DIR"

python3 "$DSA_IOS_ROOT/scripts/fixture-server.py" --quote-delay 2 --ready-file "$DSA_EVIDENCE_DIR/fixture-ready.json" > "$DSA_EVIDENCE_DIR/fixture.log" 2>&1 &
DSA_FIXTURE_PID=$!
trap 'kill "$DSA_FIXTURE_PID" 2>/dev/null || true' EXIT

python3 - "$DSA_EVIDENCE_DIR/fixture-ready.json" <<'PY'
from pathlib import Path
import sys, time
ready = Path(sys.argv[1])
for _ in range(100):
    if ready.exists():
        break
    time.sleep(0.1)
else:
    raise SystemExit("fixture 未啟動，請檢查 fixture.log")
PY

xcodegen generate --spec "$DSA_IOS_ROOT/project.yml" --project "$DSA_IOS_ROOT" --quiet
DSA_SIGNING_ARGS=(CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=-)
if [[ -n "${DSA_TEAM_ID:-}" ]]; then DSA_SIGNING_ARGS+=("DEVELOPMENT_TEAM=$DSA_TEAM_ID"); fi
xcodebuild build-for-testing -project "$DSA_IOS_ROOT/DSAMarket.xcodeproj" -scheme DSAMarket \
  -configuration Debug -destination "platform=iOS Simulator,id=$DSA_SIMULATOR_ID" \
  -derivedDataPath "$DSA_EVIDENCE_DIR/DerivedData" "${DSA_SIGNING_ARGS[@]}" \
  > "$DSA_EVIDENCE_DIR/build.log" 2>&1

DSA_TEST_RUN="$(python3 - "$DSA_EVIDENCE_DIR" <<'PY'
from pathlib import Path
import json, plistlib, sys
root = Path(sys.argv[1])
ready = json.loads((root / "fixture-ready.json").read_text())
files = list((root / "DerivedData/Build/Products").glob("*.xctestrun"))
if len(files) != 1:
    raise SystemExit(f"預期唯一 xctestrun，實際 {len(files)} 個")
path = files[0]
with path.open("rb") as stream:
    config = plistlib.load(stream)
if "TestConfigurations" in config:
    targets = [target for item in config["TestConfigurations"] for target in item["TestTargets"]]
else:
    targets = [value for key, value in config.items() if not key.startswith("__") and isinstance(value, dict)]
for target in targets:
    target.setdefault("EnvironmentVariables", {})["DSA_TEST_SERVER"] = ready["url"]
    target.setdefault("UITargetAppEnvironmentVariables", {})["DSA_TEST_SERVER"] = ready["url"]
with path.open("wb") as stream:
    plistlib.dump(config, stream)
print(path)
PY
)"

python3 - "$DSA_TEST_RUN" "$DSA_SIMULATOR_ID" "$DSA_EVIDENCE_DIR" <<'PY'
from pathlib import Path
import json, re, shutil, signal, subprocess, sys, time
test_run, simulator, directory = sys.argv[1:]
root = Path(directory)
log_path = root / "test.log"
command = ["xcodebuild", "test-without-building", "-xctestrun", test_run,
           "-destination", f"platform=iOS Simulator,id={simulator}",
           "-resultBundlePath", str(root / "UITests.xcresult"), "-parallel-testing-enabled", "NO"]
finished_at = None
timed_out = False
with log_path.open("w") as log:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    while process.poll() is None:
        # 已觀察到的 SDK/runtime finalize 卡住；只在 UI suite 已結束後啟動 60 秒上限。
        output = log_path.read_text(errors="replace")
        if finished_at is None and re.search(r"Test Suite 'DSAMarketUITests.xctest' (passed|failed)", output):
            finished_at = time.monotonic()
        if finished_at is not None and time.monotonic() - finished_at > 60:
            timed_out = True
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            break
        time.sleep(1)
output = log_path.read_text(errors="replace")
for index, path in enumerate(dict.fromkeys(re.findall(r"DSA_UI_EVIDENCE_DIR=(.+)", output))):
    source = Path(path.strip())
    if source.is_dir() and source.parent.name == "DSA-UI-Evidence":
        shutil.copytree(source, root / f"screenshots-{index + 1}", dirs_exist_ok=True)
status = {"exit_code": process.returncode, "finalization_timeout": timed_out,
          "ui_suite_passed": bool(re.search(r"Test Suite 'DSAMarketUITests.xctest' passed", output))}
(root / "test-status.json").write_text(json.dumps(status, indent=2) + "\n")
if timed_out:
    print("UI suite 已結束，但 Xcode 結果封存超時；保留 test.log 與獨立 PNG，不視為整體驗收通過。", file=sys.stderr)
    raise SystemExit(124)
raise SystemExit(process.returncode)
PY
echo "UI fixture 驗收完成；結果：$DSA_EVIDENCE_DIR/UITests.xcresult"
