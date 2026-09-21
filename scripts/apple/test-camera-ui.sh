#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../native/ios"
xcodegen generate --spec project.yml
dishplay_runtime=$(xcrun simctl list runtimes --json | python3 -c '
import json,sys
runtimes=[r for r in json.load(sys.stdin)["runtimes"] if r.get("isAvailable") and ".iOS-" in r["identifier"]]
if not runtimes: raise SystemExit("No installed iOS simulator runtime")
print(max(runtimes,key=lambda r:tuple(int(n) for n in r["version"].split(".")))["identifier"])
')
dishplay_simulator=$(xcrun simctl create "DishPlay Camera Checks" com.apple.CoreSimulator.SimDeviceType.iPhone-13 "$dishplay_runtime")
cleanup() {
  xcrun simctl shutdown "$dishplay_simulator" 2>/dev/null || true
  xcrun simctl delete "$dishplay_simulator" 2>/dev/null || true
}
trap cleanup EXIT
xcrun simctl boot "$dishplay_simulator"
xcrun simctl bootstatus "$dishplay_simulator" -b
mkdir -p build
set +e
xcodebuild -project DishPlayCapture.xcodeproj -scheme DishPlayCapture -configuration Debug \
  -destination "platform=iOS Simulator,id=$dishplay_simulator" -destination-timeout 90 \
  -derivedDataPath build/SimulatorDerivedData -resultBundlePath build/CameraUI.xcresult \
  -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
  -jobs 1 CODE_SIGNING_ALLOWED=NO test
dishplay_result=$?
set -e
if [ -d build/CameraUI.xcresult ]; then
  xcrun xcresulttool export attachments --path build/CameraUI.xcresult --output-path build/camera-evidence || true
fi
exit "$dishplay_result"
