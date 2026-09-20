#!/usr/bin/env bash
set -euo pipefail
curl --fail --location --retry 3 \
  https://github.com/yonaskolb/XcodeGen/releases/download/2.46.0/xcodegen.zip \
  --output "$RUNNER_TEMP/xcodegen.zip"
echo "4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806  $RUNNER_TEMP/xcodegen.zip" | shasum -a 256 -c -
ditto -x -k "$RUNNER_TEMP/xcodegen.zip" "$RUNNER_TEMP/xcodegen"
python3 - <<'PY'
import os
from pathlib import Path
binaries = [p for p in (Path(os.environ['RUNNER_TEMP']) / 'xcodegen').rglob('xcodegen') if p.is_file() and os.access(p, os.X_OK)]
if len(binaries) != 1:
    raise SystemExit('Expected exactly one XcodeGen executable in the verified archive')
with open(os.environ['GITHUB_PATH'], 'a') as stream:
    stream.write(str(binaries[0].parent) + '\n')
PY
