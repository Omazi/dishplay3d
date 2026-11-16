#!/usr/bin/env python3
"""Create (or reuse) the App ID and App Store provisioning profile for DishPlay Scan
through the App Store Connect API. Runs on Linux, Windows or the CI runner: no Mac needed.

  APPLE_KEY_ID=... APPLE_ISSUER_ID=... APP_STORE_CONNECT_API_KEY="$(cat AuthKey_XXXX.p8)" \
  IOS_DISTRIBUTION_P12_BASE64=... IOS_DISTRIBUTION_P12_PASSWORD=... \
  python tools/asc_profile.py --bundle app.dishplay.capture --out profile.mobileprovision

Requirements: an App Store Connect TEAM API key allowed to manage certificates/identifiers/profiles
(Admin), and the existing Apple Distribution identity (.p12) whose certificate will be put in the
profile. Never creates or revokes certificates. Prints only identifiers, never key material.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.appstoreconnect.apple.com/v1"


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_jwt(key_id: str, issuer: str, pem: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    now = int(time.time())
    payload = {"iss": issuer, "iat": now, "exp": now + 15 * 60, "aud": "appstoreconnect-v1"}
    signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(payload).encode())}"
    der = key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return f"{signing_input}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


class ASC:
    def __init__(self, token: str):
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:600]
            raise SystemExit(f"App Store Connect API {method} {path.split('?')[0]} -> {e.code}: {detail}")


def p12_certificate_sha1(p12_b64: str, password: str) -> tuple[str, str]:
    from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
    _, cert, _ = pkcs12.load_key_and_certificates(base64.b64decode(p12_b64), password.encode())
    if cert is None:
        raise SystemExit("The PKCS#12 does not contain a certificate.")
    der = cert.public_bytes(Encoding.DER)
    return hashlib.sha1(der).hexdigest(), format(cert.serial_number, "X")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="app.dishplay.capture")
    ap.add_argument("--name", default="DishPlay Capture")
    ap.add_argument("--out", required=True)
    ap.add_argument("--github-env", action="store_true", help="also export IOS_PROVISION_PROFILE_BASE64 to $GITHUB_ENV (masked)")
    a = ap.parse_args()
    env = os.environ
    for k in ("APPLE_KEY_ID", "APPLE_ISSUER_ID", "APP_STORE_CONNECT_API_KEY", "IOS_DISTRIBUTION_P12_BASE64", "IOS_DISTRIBUTION_P12_PASSWORD"):
        if not env.get(k):
            raise SystemExit(f"Missing {k} (see docs/TESTFLIGHT.md)")
    asc = ASC(make_jwt(env["APPLE_KEY_ID"], env["APPLE_ISSUER_ID"], env["APP_STORE_CONNECT_API_KEY"].strip() + "\n"))
    sha1, serial = p12_certificate_sha1(env["IOS_DISTRIBUTION_P12_BASE64"], env["IOS_DISTRIBUTION_P12_PASSWORD"])
    # 1. App ID
    found = asc.call("GET", f"/bundleIds?filter[identifier]={a.bundle}&limit=20").get("data", [])
    bundle = next((b for b in found if b["attributes"]["identifier"] == a.bundle), None)
    if bundle is None:
        bundle = asc.call("POST", "/bundleIds", {"data": {"type": "bundleIds", "attributes": {
            "identifier": a.bundle, "name": a.name, "platform": "IOS"}}})["data"]
        print(f"Registered App ID {a.bundle}")
    else:
        print(f"App ID {a.bundle} already registered")
    # 2. Distribution certificate matching the p12
    certs = asc.call("GET", "/certificates?filter[certificateType]=DISTRIBUTION,IOS_DISTRIBUTION&limit=200").get("data", [])
    cert = next((c for c in certs if hashlib.sha1(base64.b64decode(c["attributes"]["certificateContent"])).hexdigest() == sha1), None)
    if cert is None:
        raise SystemExit(f"No Apple Distribution certificate on the account matches the provided .p12 (serial {serial}).")
    # 3. Profile: reuse an active App Store profile for this bundle that contains this certificate, else create one
    profiles = asc.call("GET", f"/bundleIds/{bundle['id']}/profiles?limit=50").get("data", [])
    chosen = None
    for p in profiles:
        at = p["attributes"]
        if at.get("profileType") == "IOS_APP_STORE" and at.get("profileState") == "ACTIVE":
            pc = asc.call("GET", f"/profiles/{p['id']}/certificates?limit=50").get("data", [])
            if any(c["id"] == cert["id"] for c in pc):
                chosen = asc.call("GET", f"/profiles/{p['id']}")["data"]
                break
    if chosen is None:
        chosen = asc.call("POST", "/profiles", {"data": {"type": "profiles", "attributes": {
            "name": f"{a.name} App Store {time.strftime('%Y%m%d%H%M')}", "profileType": "IOS_APP_STORE"},
            "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bundle["id"]}},
                              "certificates": {"data": [{"type": "certificates", "id": cert["id"]}]}}}})["data"]
        print("Created App Store provisioning profile")
    else:
        print("Reusing active App Store provisioning profile")
    content = chosen["attributes"]["profileContent"]
    with open(a.out, "wb") as f:
        f.write(base64.b64decode(content))
    if a.github_env:
        print(f"::add-mask::{content[:40]}")
        with open(env["GITHUB_ENV"], "a") as f:
            f.write(f"IOS_PROVISION_PROFILE_BASE64={content}\n")
    print(f"Profile written to {a.out}")


if __name__ == "__main__":
    main()
