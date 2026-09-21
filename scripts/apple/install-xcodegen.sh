#!/usr/bin/env bash
# Prints the pinned executable path. No Homebrew, sudo or CI-provider dependency.
set -euo pipefail
dishplay_tools_dir=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/dishplay-xcodegen.XXXXXX")
trap 'rm -rf "$dishplay_tools_dir"' ERR
curl --fail --location --retry 3 --connect-timeout 20 --max-time 180 \
  https://github.com/yonaskolb/XcodeGen/releases/download/2.46.0/xcodegen.zip \
  --output "$dishplay_tools_dir/xcodegen.zip"
echo "4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806  $dishplay_tools_dir/xcodegen.zip" | shasum -a 256 -c - >&2
ditto -x -k "$dishplay_tools_dir/xcodegen.zip" "$dishplay_tools_dir/unpacked"
python3 - "$dishplay_tools_dir/unpacked" <<'PY'
import os
from pathlib import Path
import sys
binaries = [p for p in Path(sys.argv[1]).rglob('xcodegen') if p.is_file() and os.access(p, os.X_OK)]
if len(binaries) != 1:
    raise SystemExit('Expected exactly one XcodeGen executable in the verified archive')
print(binaries[0])
PY
