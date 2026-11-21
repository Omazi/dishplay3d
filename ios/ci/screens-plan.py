"""Reads what the screen check is asked to do (ios/UITests/RUN.txt) and prints the list of machines to start,
as `matrix=<json>` for GitHub Actions.

    only: light          one walk instead of the three (light, dark, largeText)
    devices: all         three iPhones instead of the reference one

The reference is a current iPhone with the newest iOS: every walk, plus Apple's readers on the sample USDZ.
With `devices: all`, two more machines: a 6.1-inch iPhone with iOS 18 (how the app looks without the glass of
iOS 26; light and dark walks) and the smallest screen the app runs on (light walk).
"""
import json
import re
import sys

WALKS = {"light": "test1Light", "dark": "test2Dark", "largeText": "test3LargeText"}


def main() -> None:
    text = open(sys.argv[1], encoding="utf-8").read()
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
