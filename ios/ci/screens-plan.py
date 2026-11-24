"""Reads what the screen check is asked to do (ios/UITests/RUN.txt) and prints the list of machines to start,
as `matrix=<json>` for GitHub Actions.

    only: light          one walk instead of the three (light, dark, largeText)
    devices: all         three iPhones instead of the reference one

    python3 ios/ci/screens-plan.py RUN.txt [runs.json RUN_ID]

With the list of this workflow's runs for the same commit (GitHub API) and the id of the current run, it also
prints `skip=true` when the same commit was already walked with success: a commit walked on the working branch
and then pushed to main is photographed once. (A walk still in progress does not count: if it failed, the
commit would be left without pictures while the release gate saw a "successful" run.)

The reference is a current iPhone with the newest iOS: every walk, plus Apple's readers on the sample USDZ.
With `devices: all`, two more machines: a 6.1-inch iPhone with iOS 18 (how the app looks without the glass of
iOS 26; light and dark walks) and the smallest screen the app runs on (light walk).
"""
import json
import re
import sys

WALKS = {"light": "test1Light", "dark": "test2Dark", "largeText": "test3LargeText"}


def already_walked(runs: list, this_run: int) -> bool:
    """Another run of this workflow succeeded on the same commit."""
    return any(int(r["id"]) != int(this_run) and r.get("conclusion") == "success" for r in runs)


def main() -> None:
    text = open(sys.argv[1], encoding="utf-8").read()
    if len(sys.argv) >= 4:
        runs = json.load(open(sys.argv[2], encoding="utf-8")).get("workflow_runs", [])
        print("skip=" + ("true" if already_walked(runs, int(sys.argv[3])) else "false"))
    asked = dict(re.findall(r"^(only|devices):[ \t]*(\S+)[ \t]*$", text, re.M))
    only = asked.get("only", "")
    if only and only not in WALKS:
        sys.exit(f"unknown walk {only!r}: expected one of {', '.join(WALKS)}")
    only = WALKS.get(only, "")
    devices = asked.get("devices", "reference")
    if devices not in ("reference", "all"):
        sys.exit(f"unknown devices {devices!r}: expected reference or all")
    matrix = [{"label": "iPhone 17 Pro, newest iOS", "slug": "reference", "device": "", "ios": "", "walks": only, "usdz": True}]
    if devices == "all":
        matrix += [
            {"label": "iPhone 16e, iOS 18", "slug": "ios18", "device": "iPhone 16e", "ios": "18",
             "walks": only or f"{WALKS['light']} {WALKS['dark']}", "usdz": False},
            {"label": "iPhone SE, newest iOS", "slug": "small", "device": "iPhone SE (3rd generation)", "ios": "",
             "walks": only or WALKS["light"], "usdz": False},
        ]
    print("matrix=" + json.dumps(matrix, separators=(",", ":")))


if __name__ == "__main__":
    main()
