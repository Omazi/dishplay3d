"""Which jobs of the checks a push needs (workflow ios-check.yml, job "gate"). Prints `run=`, `backend=` and
`ios=` for GitHub Actions.

    git diff --name-only BEFORE AFTER | python3 ios/ci/check-plan.py
    environment: RELEASE_CALL  "true" when the TestFlight workflow calls the checks for a release
                 EVENT         github.event_name
                 KNOWN         "true" when the list of changed files on the input is reliable

A push that only changes documents needs no machine at all, and a push that only changes the calculator needs no
Mac: on a private repository every minute is paid, and a Mac minute costs ten times a Linux one. Everything runs
when in doubt: a release, a manual start, a pull request, or a push whose changes cannot be listed.
A push that changes ios/RELEASE_NOTES.txt is a release: the TestFlight workflow runs the same checks itself.
"""
import os
import sys

BACKEND = ("backend/", "tools/", "contracts/", "colab/", "compliance/", "ios/ci/", "ios/ScanCore/Tests/ScanCoreTests/Vectors/")
IOS = ("ios/", ".github/workflows/")
NOT_THE_APP = ("ios/RELEASE_NOTES.txt", "ios/UITests/RUN.txt", "ios/UITests/audit-baseline.txt")


def plan(changed, release_call: bool, event: str, known: bool) -> dict:
    if release_call or event != "push" or not known:
        return {"run": True, "backend": True, "ios": True, "why": "everything (release, manual start, pull request, or changes unknown)"}
    if "ios/RELEASE_NOTES.txt" in changed:
        return {"run": False, "backend": False, "ios": False, "why": "release push: the same checks run inside the TestFlight workflow"}
    backend = any(f.startswith(BACKEND) or f == ".github/workflows/ios-check.yml" for f in changed)
    ios = any(f.startswith(IOS) and f not in NOT_THE_APP for f in changed)
    why = ", ".join(name for name, on in (("calculator", backend), ("app", ios)) if on) or "nothing to check (documents only)"
    return {"run": backend or ios, "backend": backend, "ios": ios, "why": why}


def main() -> None:
    changed = [line.strip() for line in sys.stdin if line.strip()]
    p = plan(changed, os.environ.get("RELEASE_CALL") == "true", os.environ.get("EVENT", ""), os.environ.get("KNOWN") == "true")
    print(f"checks: {p['why']}", file=sys.stderr)
    for key in ("run", "backend", "ios"):
        print(f"{key}={'true' if p[key] else 'false'}")


if __name__ == "__main__":
    main()
