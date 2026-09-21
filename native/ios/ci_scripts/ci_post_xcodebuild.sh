#!/usr/bin/env bash
set -euo pipefail
: "${CI_XCODEBUILD_ACTION:?Missing Xcode Cloud action}"
: "${CI_XCODEBUILD_EXIT_CODE:?Missing Xcode Cloud build result}"
if [[ "$CI_XCODEBUILD_EXIT_CODE" != 0 ]]; then
  echo "Xcode build failed; release bundle validation cannot pass." >&2
  exit 1
fi
if [[ "$CI_XCODEBUILD_ACTION" == archive ]]; then
  : "${CI_ARCHIVE_PATH:?Missing archive path}"
  # Xcode Cloud preserves the linked validator alongside this script for later phases.
  python3 "$(dirname "$0")/validate-bundle.py" "$CI_ARCHIVE_PATH/Products/Applications/DishPlayCapture.app"
fi
