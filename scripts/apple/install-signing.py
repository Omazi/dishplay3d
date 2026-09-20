#!/usr/bin/env python3
"""Install already-issued Apple signing material on an ephemeral macOS runner.

Never creates or revokes certificates. Private material is kept in RUNNER_TEMP,
not the checkout/artifacts. Required values come from GitHub secrets/variables.
"""
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shlex
import subprocess
import sys


def require(name, pattern=None):
    value = os.environ.get(name, '')
    if not value or (pattern and not re.fullmatch(pattern, value)):
        raise ValueError(f'Missing or invalid {name}; see docs/testflight.md.')
    return value


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        # Command arguments may contain a temporary keychain password. Never echo them.
        raise RuntimeError(f'{Path(args[0]).name} failed while preparing signing (exit {result.returncode}).')
    return result.stdout


def secret_file(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(value)


def validate_profile(profile, team, bundle):
    expiry = profile.get('ExpirationDate')
    if not isinstance(expiry, dt.datetime) or expiry.replace(tzinfo=dt.timezone.utc) <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1):
        raise ValueError('The provisioning profile expires within one day or is already expired.')
    if profile.get('TeamIdentifier') != [team]:
        raise ValueError('The profile belongs to another Apple team.')
    if not re.fullmatch(r'[A-Fa-f0-9-]{36}', profile.get('UUID', '')):
        raise ValueError('The profile UUID is invalid.')
    entitlements = profile.get('Entitlements', {})
    if entitlements.get('application-identifier') != f'{team}.{bundle}':
        raise ValueError('The profile does not match the exact bundle identifier and team.')
    if (entitlements.get('get-task-allow', True) or not entitlements.get('beta-reports-active')
            or 'ProvisionedDevices' in profile or profile.get('ProvisionsAllDevices')):
        raise ValueError('Use an App Store distribution profile, not development, Ad Hoc or Enterprise.')
    return profile['UUID']


def main():
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Signing installation runs only on the hosted macOS GitHub runner.')
    team = require('APPLE_TEAM_ID', r'[A-Z0-9]{10}')
    bundle = require('IOS_BUNDLE_ID', r'[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+')
    key_id = require('APPLE_KEY_ID', r'[A-Z0-9]{10}')
    require('APPLE_ISSUER_ID', r'[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}')
    require('IOS_DISTRIBUTION_P12_PASSWORD')
    key = require('APP_STORE_CONNECT_API_KEY').strip() + '\n'
    if not key.startswith('-----BEGIN PRIVATE KEY-----') or not key.rstrip().endswith('-----END PRIVATE KEY-----'):
        raise ValueError('APP_STORE_CONNECT_API_KEY must contain the original .p8 PEM text.')
    p12 = base64.b64decode(require('IOS_DISTRIBUTION_P12_BASE64'), validate=True)
    profile_bytes = base64.b64decode(require('IOS_PROVISION_PROFILE_BASE64'), validate=True)
    folder = Path(require('RUNNER_TEMP')) / 'dishplay-apple-signing'
    folder.mkdir(mode=0o700, exist_ok=False)
    profile_path = folder / 'profile.mobileprovision'
    p12_path = folder / 'distribution.p12'
    api_key = folder / f'AuthKey_{key_id}.p8'
    secret_file(profile_path, profile_bytes)
    secret_file(p12_path, p12)
    secret_file(api_key, key.encode())
    run(['openssl', 'pkey', '-in', str(api_key), '-check', '-noout'])
    profile = plistlib.loads(run(['security', 'cms', '-D', '-i', str(profile_path)]))
    profile_uuid = validate_profile(profile, team, bundle)
    keychain = folder / 'signing.keychain-db'
    original_search = shlex.split(run(['security', 'list-keychains', '-d', 'user']).decode())
    secret_file(folder / 'original-keychains.json', json.dumps(original_search).encode())
    password = secrets.token_urlsafe(32)
    run(['security', 'create-keychain', '-p', password, str(keychain)])
    run(['security', 'set-keychain-settings', '-lut', '3600', str(keychain)])
    run(['security', 'unlock-keychain', '-p', password, str(keychain)])
    run(['security', 'import', str(p12_path), '-P', os.environ['IOS_DISTRIBUTION_P12_PASSWORD'], '-k', str(keychain), '-T', '/usr/bin/codesign', '-T', '/usr/bin/security'])
    run(['security', 'set-key-partition-list', '-S', 'apple-tool:,apple:,codesign:', '-k', password, str(keychain)])
    run(['security', 'list-keychains', '-d', 'user', '-s', str(keychain), *original_search])
    identities = run(['security', 'find-identity', '-v', '-p', 'codesigning', str(keychain)]).decode()
    cert_hashes = {hashlib.sha1(cert).hexdigest().upper() for cert in profile.get('DeveloperCertificates', [])}
    if not any('Apple Distribution:' in line and any(cert_hash in line for cert_hash in cert_hashes) for line in identities.splitlines()):
        raise ValueError('No valid Apple Distribution private key matches this provisioning profile.')
    installed_profiles = []
    secret_file(folder / 'installed-profiles.json', b'[]')
    # Xcode 16+ uses this location; also install in the older path for compatible tools.
    for relative in ['Library/Developer/Xcode/UserData/Provisioning Profiles', 'Library/MobileDevice/Provisioning Profiles']:
        directory = Path.home() / relative
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f'{profile_uuid}.mobileprovision'
        if destination.exists():
            raise ValueError('The ephemeral runner already contains this profile; refusing to overwrite it.')
        secret_file(destination, profile_bytes)
        installed_profiles.append(str(destination))
        (folder / 'installed-profiles.json').write_text(json.dumps(installed_profiles))
    export = {'method': 'app-store-connect', 'destination': 'export', 'teamID': team,
              'signingStyle': 'manual', 'signingCertificate': 'Apple Distribution',
              'provisioningProfiles': {bundle: profile_uuid}, 'uploadSymbols': True,
              'manageAppVersionAndBuildNumber': False}
    secret_file(folder / 'ExportOptions.plist', plistlib.dumps(export))
    with open(require('GITHUB_ENV'), 'a') as stream:
        stream.write(f'APPLE_API_KEY_PATH={api_key}\nSIGNING_PROFILE_UUID={profile_uuid}\nSIGNING_KEYCHAIN={keychain}\nAPPLE_EXPORT_OPTIONS={folder / "ExportOptions.plist"}\n')
    print('Apple signing material validated and installed in the temporary runner keychain.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not include a traceback: it can expose subprocess arguments or secret values.
        print(f'::error::{error}', file=sys.stderr)
        sys.exit(1)
