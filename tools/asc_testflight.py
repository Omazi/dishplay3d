#!/usr/bin/env python3
"""After an upload: wait until Apple has processed the build, report its real state, set the
export-compliance answer (no non-exempt encryption: HTTPS only), add French test notes and assign
the build to the internal TestFlight group so testers see it.

  APPLE_KEY_ID=... APPLE_ISSUER_ID=... APP_STORE_CONNECT_API_KEY=... \
  python tools/asc_testflight.py --bundle app.dishplay.capture --group "DishPlay - Tests iPhone" [--build 6.1]
Without --build, the most recently uploaded build is used.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc_profile import ASC, make_jwt  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="app.dishplay.capture")
    ap.add_argument("--group", default="DishPlay - Tests iPhone")
    ap.add_argument("--build", help="build number (CFBundleVersion), default: latest uploaded")
    ap.add_argument("--notes", default=str(Path(__file__).resolve().parents[1] / "ios" / "RELEASE_NOTES.txt"))
    ap.add_argument("--wait-min", type=float, default=40)
    ap.add_argument("--max-age-h", type=float, default=3, help="with --build: ignore uploads older than this")
    a = ap.parse_args()
    env = os.environ
    for k in ("APPLE_KEY_ID", "APPLE_ISSUER_ID", "APP_STORE_CONNECT_API_KEY"):
        if not env.get(k):
            raise SystemExit(f"Missing {k}")

    def client():
        return ASC(make_jwt(env["APPLE_KEY_ID"], env["APPLE_ISSUER_ID"], env["APP_STORE_CONNECT_API_KEY"].strip() + "\n"))

    asc = client()
    apps = asc.call("GET", f"/apps?filter[bundleId]={a.bundle}").get("data", [])
    if not apps:
        raise SystemExit(f"No App Store Connect app with bundle {a.bundle}")
    app = apps[0]
    print(f"App: {app['attributes'].get('name')} ({app['id']})")
    deadline = time.time() + a.wait_min * 60
    build = None
    while True:
        asc = client()  # tokens live 15 min
        q = f"/builds?filter[app]={app['id']}&sort=-uploadedDate&limit=10&include=preReleaseVersion"
        if a.build:
            q += f"&filter[version]={a.build}"
        res = asc.call("GET", q)
        versions = {i["id"]: i["attributes"].get("version") for i in res.get("included", []) if i["type"] == "preReleaseVersions"}
        builds = res.get("data", [])
        if a.build:
            # Old versions reused the same build numbers (e.g. 0.6.0 (10.1)): only accept a recent upload.
            import datetime as dt
            recent = []
            for b in builds:
                up = b["attributes"].get("uploadedDate")
                try:
                    age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(up)
                except (TypeError, ValueError):
                    continue
                if age < dt.timedelta(hours=a.max_age_h):
                    recent.append(b)
            builds = recent
        if builds:
            build = builds[0]
            at = build["attributes"]
            prv = (build.get("relationships", {}).get("preReleaseVersion", {}).get("data") or {}).get("id")
            print(f"Build {versions.get(prv, '?')} ({at.get('version')}) uploaded {at.get('uploadedDate')}: "
                  f"processingState={at.get('processingState')} expired={at.get('expired')}")
            state = at.get("processingState")
            if state in ("FAILED", "INVALID"):
                raise SystemExit(f"::error::Apple marked the build {state}. Check the e-mail sent to the account holder for the reason.")
            if state == "VALID":
                break
        else:
            print("Build not visible yet")
        if time.time() > deadline:
            raise SystemExit("::error::Build still not processed after the waiting time")
        time.sleep(30)
    bid = build["id"]
    if build["attributes"].get("usesNonExemptEncryption") is None:
        asc.call("PATCH", f"/builds/{bid}", {"data": {"type": "builds", "id": bid, "attributes": {"usesNonExemptEncryption": False}}})
        print("Export compliance set: no non-exempt encryption (HTTPS only)")
    notes = Path(a.notes).read_text(encoding="utf-8")[:3900] if Path(a.notes).exists() else ""
    if notes:
        locs = asc.call("GET", f"/builds/{bid}/betaBuildLocalizations").get("data", [])
        fr = next((l for l in locs if l["attributes"].get("locale", "").startswith("fr")), None)
        if fr:
            asc.call("PATCH", f"/betaBuildLocalizations/{fr['id']}", {"data": {"type": "betaBuildLocalizations", "id": fr["id"],
                                                                              "attributes": {"whatsNew": notes}}})
        else:
            asc.call("POST", "/betaBuildLocalizations", {"data": {"type": "betaBuildLocalizations",
                                                                   "attributes": {"locale": "fr-FR", "whatsNew": notes},
                                                                   "relationships": {"build": {"data": {"type": "builds", "id": bid}}}}})
        print("Test notes (fr-FR) set")
    groups = asc.call("GET", f"/apps/{app['id']}/betaGroups?limit=50").get("data", [])
    print("Groups:", ", ".join(f"{g['attributes'].get('name')} (internal={g['attributes'].get('isInternalGroup')})" for g in groups))
    group = next((g for g in groups if g["attributes"].get("name") == a.group), None)
    if group is None:
        raise SystemExit(f"::error::TestFlight group '{a.group}' not found")
    asc.call("POST", f"/betaGroups/{group['id']}/relationships/builds", {"data": [{"type": "builds", "id": bid}]})
    print(f"Build {build['attributes'].get('version')} added to '{a.group}'. Testers can now update in TestFlight.")


if __name__ == "__main__":
    main()
