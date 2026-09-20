#!/usr/bin/env python3
"""Check the release bundle before either unsigned delivery or TestFlight export."""
from pathlib import Path
import plistlib
import sys

app = Path(sys.argv[1])
info = plistlib.loads((app / 'Info.plist').read_bytes())
assert info['CFBundlePackageType'] == 'APPL'
assert info['DTSDKName'].startswith('iphoneos')
assert int(info['DTSDKName'].removeprefix('iphoneos').split('.')[0]) >= 26, 'App Store Connect requires iOS SDK 26 or newer.'
assert info.get('CFBundleIcons', {}).get('CFBundlePrimaryIcon', {}).get('CFBundleIconName') == 'AppIcon', 'Missing compiled application icon.'
assert (app / 'Assets.car').is_file(), 'Missing asset catalogue.'
assert 'fr' in info['CFBundleLocalizations'] and 'en' in info['CFBundleLocalizations']
assert 'capture' in info['NSCameraUsageDescription'].lower()
privacy = plistlib.loads((app / 'PrivacyInfo.xcprivacy').read_bytes())
assert privacy['NSPrivacyTracking'] is False
assert any(item['NSPrivacyAccessedAPIType'] == 'NSPrivacyAccessedAPICategoryFileTimestamp' and 'C617.1' in item['NSPrivacyAccessedAPITypeReasons'] for item in privacy['NSPrivacyAccessedAPITypes'])
assert (app / 'fr.lproj/Localizable.strings').is_file()
assert not list(app.rglob('*.p8')) and not list(app.rglob('*.p12')), 'Signing secrets must never be packaged.'
print(f'Release bundle validated: {info["CFBundleIdentifier"]}, version {info["CFBundleShortVersionString"]} ({info["CFBundleVersion"]}), {info["DTSDKName"]}.')
