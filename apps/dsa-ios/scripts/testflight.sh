#!/bin/bash
# 使用現有 Apple 登入或 ASC 金鑰封存；--upload 才會傳送到 TestFlight。
set -euo pipefail
DSA_IOS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DSA_MODE="${1:---archive}"
if [[ "$DSA_MODE" != "--archive" && "$DSA_MODE" != "--upload" ]]; then
  echo '用法：bash scripts/testflight.sh [--archive|--upload]' >&2
  exit 2
fi
: "${DSA_TEAM_ID:?請設定 Apple Developer Team ID}"
: "${DSA_SERVER_URL:?請設定手機可達的 HTTPS 分析服務網址}"
python3 - "$DSA_SERVER_URL" <<'PY'
import sys
from urllib.parse import urlsplit
url = urlsplit(sys.argv[1])
if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
    raise SystemExit('正式服務網址必須是無帳密、無查詢參數的 HTTPS URL')
PY
# Xcode 匯出預期系統 rsync，避免 Homebrew 版本改變複製語意。
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
DSA_BUILD_NUMBER="${DSA_BUILD_NUMBER:-$(date +%Y%m%d%H%M)}"
DSA_OUTPUT="$DSA_IOS_ROOT/build/testflight-$DSA_BUILD_NUMBER"
mkdir -p "$DSA_OUTPUT"
DSA_AUTH=(-allowProvisioningUpdates)
if [[ -n "${ASC_KEY_PATH:-}" || -n "${ASC_KEY_ID:-}" || -n "${ASC_ISSUER_ID:-}" ]]; then
  : "${ASC_KEY_PATH:?ASC 金鑰設定需同時提供 PATH、ID、ISSUER_ID}"
  : "${ASC_KEY_ID:?ASC 金鑰設定需同時提供 PATH、ID、ISSUER_ID}"
  : "${ASC_ISSUER_ID:?ASC 金鑰設定需同時提供 PATH、ID、ISSUER_ID}"
  [[ -f "$ASC_KEY_PATH" ]] || { echo '找不到 ASC 金鑰檔案' >&2; exit 2; }
  DSA_AUTH+=(-authenticationKeyPath "$ASC_KEY_PATH" -authenticationKeyID "$ASC_KEY_ID" -authenticationKeyIssuerID "$ASC_ISSUER_ID")
fi
xcodegen generate --spec "$DSA_IOS_ROOT/project.yml" --project "$DSA_IOS_ROOT" --quiet
echo "正在封存 build ${DSA_BUILD_NUMBER}；日誌：${DSA_OUTPUT}/archive.log"
if ! xcodebuild -project "$DSA_IOS_ROOT/DSAMarket.xcodeproj" -scheme DSAMarket \
  -configuration Release -destination 'generic/platform=iOS' \
  -archivePath "$DSA_OUTPUT/DSAMarket.xcarchive" \
  DEVELOPMENT_TEAM="$DSA_TEAM_ID" DSA_SERVER_URL="$DSA_SERVER_URL" \
  DSA_PREVIOUS_SERVER_URL="${DSA_PREVIOUS_SERVER_URL:-}" \
  CURRENT_PROJECT_VERSION="$DSA_BUILD_NUMBER" "${DSA_AUTH[@]}" archive \
  > "$DSA_OUTPUT/archive.log" 2>&1; then
  tail -35 "$DSA_OUTPUT/archive.log" >&2
  exit 1
fi
if [[ "$DSA_MODE" == '--archive' ]]; then
  echo "封存完成：$DSA_OUTPUT/DSAMarket.xcarchive（尚未上傳）"
  exit 0
fi
python3 - "$DSA_OUTPUT/ExportOptions.plist" "$DSA_TEAM_ID" <<'PY'
import plistlib, sys
with open(sys.argv[1], 'wb') as stream:
    plistlib.dump({'method': 'app-store-connect', 'destination': 'upload',
                  'teamID': sys.argv[2], 'signingStyle': 'automatic',
                  'manageAppVersionAndBuildNumber': False, 'uploadSymbols': True,
                  'testFlightInternalTestingOnly': True}, stream)
PY
if ! xcodebuild -exportArchive -archivePath "$DSA_OUTPUT/DSAMarket.xcarchive" \
  -exportOptionsPlist "$DSA_OUTPUT/ExportOptions.plist" -exportPath "$DSA_OUTPUT/export" \
  "${DSA_AUTH[@]}" > "$DSA_OUTPUT/export.log" 2>&1; then
  tail -35 "$DSA_OUTPUT/export.log" >&2
  exit 1
fi
echo "上傳完成，build ${DSA_BUILD_NUMBER}；仍需核對 Apple 處理成功並加入內部測試群組。"
