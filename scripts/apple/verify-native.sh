#!/usr/bin/env bash
# The same serial native checks run on GitHub's Mac and on Xcode Cloud.
set -euo pipefail
cd "$(dirname "$0")/../.."
dishplay_checks_dir=$(mktemp -d "${TMPDIR:-/tmp}/dishplay-native-checks.XXXXXX")
trap 'rm -rf "$dishplay_checks_dir"' EXIT
dishplay_sources=native/ios/DishPlayCapture
dishplay_tests=native/ios/Tests

swiftc "$dishplay_sources/ScanCoverage.swift" "$dishplay_tests/main.swift" -o "$dishplay_checks_dir/coverage"
"$dishplay_checks_dir/coverage"
swiftc -parse-as-library "$dishplay_sources/ScanCameraHealth.swift" "$dishplay_sources/ScanDiagnostics.swift" "$dishplay_tests/ScanCameraHealthTests.swift" -o "$dishplay_checks_dir/camera"
"$dishplay_checks_dir/camera"
swiftc -parse-as-library "$dishplay_sources/CaptureDelivery.swift" "$dishplay_tests/CaptureDeliveryTests.swift" -o "$dishplay_checks_dir/receipts"
"$dishplay_checks_dir/receipts"
swiftc -parse-as-library -target "$(uname -m)-apple-macosx15.0" "$dishplay_sources/ScanMovieRecorder.swift" "$dishplay_tests/ScanMovieTests.swift" -o "$dishplay_checks_dir/movie"
"$dishplay_checks_dir/movie"
swiftc -parse-as-library -target "$(uname -m)-apple-macosx15.0" "$dishplay_sources/VideoFrameExtractor.swift" "$dishplay_tests/VideoExtractionTests.swift" -o "$dishplay_checks_dir/video"
"$dishplay_checks_dir/video"
swiftc -O -parse-as-library "$dishplay_sources/ScanVolume.swift" "$dishplay_sources/ScanPreview.swift" "$dishplay_tests/ScanPreviewTests.swift" -o "$dishplay_checks_dir/preview"
"$dishplay_checks_dir/preview"
swiftc -O -parse-as-library "$dishplay_sources/ScanVolume.swift" "$dishplay_sources/ScanPreview.swift" "$dishplay_tests/ScanVolumeTests.swift" -o "$dishplay_checks_dir/volume"
"$dishplay_checks_dir/volume"
swiftc -parse-as-library "$dishplay_sources/ScanImageMask.swift" "$dishplay_tests/ScanImageMaskTests.swift" -o "$dishplay_checks_dir/mask"
"$dishplay_checks_dir/mask"
python3 scripts/apple/test_signing.py
