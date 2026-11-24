#!/usr/bin/env bash
# Prints the developer directory of the Xcode every workflow of the app uses: the newest installed one of the
# major version below. This is the one place to change when the project moves to the next Xcode
# (docs/TESTFLIGHT.md, the April 2027 deadline); XCODE_MAJOR can also be set for a trial build.
#   DEVELOPER_DIR=$(bash ios/ci/select-xcode.sh)
set -euo pipefail
MAJOR="${XCODE_MAJOR:-26}"
APPS="${XCODE_APPS_DIR:-/Applications}"   # another folder only in the tests of this script
XC=$( (ls -d "$APPS"/Xcode_"$MAJOR"*.app 2>/dev/null || true) | sort -V | tail -1)
if [ -z "$XC" ]; then
  echo "no Xcode $MAJOR on this machine; installed: $( (ls -d "$APPS"/Xcode*.app 2>/dev/null || true) | xargs -n1 basename 2>/dev/null | tr '\n' ' ')" >&2
  exit 1
fi
echo "$XC/Contents/Developer"
