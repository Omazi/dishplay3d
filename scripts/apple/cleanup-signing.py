#!/usr/bin/env python3
"""Remove only this workflow's temporary credentials and profiles."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

folder = Path(os.environ['RUNNER_TEMP']) / 'dishplay-apple-signing'
if folder.is_dir():
    original = folder / 'original-keychains.json'
    if original.exists():
        subprocess.run(['security', 'list-keychains', '-d', 'user', '-s', *json.loads(original.read_text())], capture_output=True, check=False)
    keychain = folder / 'signing.keychain-db'
    if keychain.exists():
        subprocess.run(['security', 'delete-keychain', str(keychain)], capture_output=True, check=False)
    manifest = folder / 'installed-profiles.json'
    allowed = {Path.home() / relative for relative in ['Library/Developer/Xcode/UserData/Provisioning Profiles', 'Library/MobileDevice/Provisioning Profiles']}
    if manifest.exists():
        for value in json.loads(manifest.read_text()):
            profile = Path(value)
            if profile.parent in allowed and re.fullmatch(r'[A-Fa-f0-9-]{36}\.mobileprovision', profile.name):
                profile.unlink(missing_ok=True)
    shutil.rmtree(folder)
print('Temporary Apple signing material removed.')
