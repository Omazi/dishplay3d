#!/usr/bin/env bash
set -euo pipefail
: "${CI_PRIMARY_REPOSITORY_PATH:?Xcode Cloud must provide the checked-out repository.}"
cd "$CI_PRIMARY_REPOSITORY_PATH"
# project.yml remains canonical, including newly added Swift files and shared schemes.
dishplay_xcodegen=$(bash scripts/apple/install-xcodegen.sh)
"$dishplay_xcodegen" generate --spec native/ios/project.yml
# Source files are available in this phase. Any failed check stops the action.
bash scripts/apple/verify-native.sh
