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

python3 "$DSA_IOS_ROOT/scripts/fixture-server.py" --ready-file "$DSA_EVIDENCE_DIR/fixture-ready.json" > "$DSA_EVIDENCE_DIR/fixture.log" 2>&1 &
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
xcodebuild build-for-testing -project "$DSA_IOS_ROOT/DSAMarket.xcodeproj" -scheme DSAMarket \
  -configuration Debug -destination "platform=iOS Simulator,id=$DSA_SIMULATOR_ID" \
  -derivedDataPath "$DSA_EVIDENCE_DIR/DerivedData" CODE_SIGNING_ALLOWED=NO \
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

xcodebuild test-without-building -xctestrun "$DSA_TEST_RUN" \
  -destination "platform=iOS Simulator,id=$DSA_SIMULATOR_ID" \
  -resultBundlePath "$DSA_EVIDENCE_DIR/UITests.xcresult" \
  -parallel-testing-enabled NO \
  > "$DSA_EVIDENCE_DIR/test.log" 2>&1
echo "UI fixture 驗收完成；結果：$DSA_EVIDENCE_DIR/UITests.xcresult"
