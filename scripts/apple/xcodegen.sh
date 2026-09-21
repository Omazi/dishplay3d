#!/usr/bin/env bash
set -euo pipefail
: "${GITHUB_PATH:?This wrapper is for GitHub Actions; use install-xcodegen.sh elsewhere.}"
dishplay_xcodegen=$(bash "$(dirname "$0")/install-xcodegen.sh")
dirname "$dishplay_xcodegen" >> "$GITHUB_PATH"
