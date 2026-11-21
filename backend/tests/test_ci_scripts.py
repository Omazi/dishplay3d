"""The two small scripts of the app's screen check (ios/ci) that decide what GitHub runs: which machines and
walks, and which simulator. They only ever run on GitHub, so their rules are pinned here."""
import json
import subprocess
import sys
from pathlib import Path

CI = Path(__file__).resolve().parents[2] / "ios" / "ci"

DEVICES = {"devices": {
    "com.apple.CoreSimulator.SimRuntime.iOS-18-5": [{"name": "iPhone 16e", "udid": "E5", "isAvailable": True}],
    "com.apple.CoreSimulator.SimRuntime.iOS-18-6": [{"name": "iPhone 16e", "udid": "E6", "isAvailable": True},
                                                    {"name": "iPhone 16", "udid": "S6", "isAvailable": True}],
    "com.apple.CoreSimulator.SimRuntime.iOS-26-2": [{"name": "iPhone Air", "udid": "AIR", "isAvailable": True},
                                                    {"name": "iPhone 17 Pro", "udid": "PRO", "isAvailable": True},
                                                    {"name": "iPhone 17", "udid": "OFF", "isAvailable": False},
                                                    {"name": "iPhone SE (3rd generation)", "udid": "SE", "isAvailable": True},
                                                    {"name": "iPad Pro", "udid": "PAD", "isAvailable": True}],
    "com.apple.CoreSimulator.SimRuntime.watchOS-26-2": [{"name": "iPhone 17 Pro", "udid": "WATCH", "isAvailable": True}],
}}


def pick(*args):
    return subprocess.run([sys.executable, str(CI / "pick-simulator.py"), *args], input=json.dumps(DEVICES),
                          capture_output=True, text=True)


def plan(tmp_path, text):
    f = tmp_path / "RUN.txt"
    f.write_text(text)
    r = subprocess.run([sys.executable, str(CI / "screens-plan.py"), str(f)], capture_output=True, text=True)
    return r, (json.loads(r.stdout.split("matrix=", 1)[1]) if r.returncode == 0 else None)


def test_the_simulator_is_the_newest_ios_and_a_current_iphone_unless_asked_otherwise():
    assert pick().stdout.strip() == "PRO"                                   # newest iOS, preferred model, never an iPad
    assert pick("", "").stdout.strip() == "PRO"                             # empty arguments mean "no wish"
    assert pick("18").stdout.strip() == "S6"                                # newest iOS 18
    assert pick("18", "iPhone 16e").stdout.strip() == "E6"                  # that model, newest iOS 18
    assert pick("", "iPhone SE (3rd generation)").stdout.strip() == "SE"
    missing = pick("17", "iPhone 13")
    assert missing.returncode != 0 and "iPhone 13" in missing.stderr


def test_the_plan_is_one_machine_and_every_walk_unless_the_file_asks_for_more_or_less(tmp_path):
    r, m = plan(tmp_path, 'An explanation that mentions "only: light" and "devices: all" inside a sentence.\n\nrun 7\n')
    assert r.returncode == 0 and len(m) == 1
    assert m[0]["walks"] == "" and m[0]["usdz"] is True and m[0]["device"] == "" and m[0]["ios"] == ""

    r, m = plan(tmp_path, "devices: all\n")
    assert [x["slug"] for x in m] == ["reference", "ios18", "small"]
    assert m[1]["device"] == "iPhone 16e" and m[1]["ios"] == "18" and m[1]["walks"] == "test1Light test2Dark"
    assert m[2]["walks"] == "test1Light" and not m[1]["usdz"] and not m[2]["usdz"]

    r, m = plan(tmp_path, "only: dark\ndevices: all\n")
    assert [x["walks"] for x in m] == ["test2Dark"] * 3

    r, m = plan(tmp_path, "only: night\n")
    assert r.returncode != 0 and "night" in r.stderr
