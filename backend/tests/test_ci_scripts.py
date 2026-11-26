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
                                                    {"name": "iPad Pro 13-inch (M5)", "udid": "PAD13", "isAvailable": True},
                                                    {"name": "iPad (A16)", "udid": "PAD", "isAvailable": True},
                                                    {"name": "iPad mini (A17 Pro)", "udid": "MINI", "isAvailable": True}],
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
    assert pick("", "iPad*").stdout.strip() == "PAD"                        # any iPad, one of the usual size first
    assert pick("", "iPad Pro*").stdout.strip() == "PAD13"
    assert pick("", "iPad mini (A17 Pro)").stdout.strip() == "MINI"         # an exact name need not be an iPhone
    assert pick("18", "iPad*").returncode != 0                              # no iPad with iOS 18 on this machine
    missing = pick("17", "iPhone 13")
    assert missing.returncode != 0 and "iPhone 13" in missing.stderr


def test_the_plan_is_one_machine_and_every_walk_unless_the_file_asks_for_more_or_less(tmp_path):
    r, m = plan(tmp_path, 'An explanation that mentions "only: light" and "devices: all" inside a sentence.\n\nrun 7\n')
    assert r.returncode == 0 and len(m) == 1
    assert m[0]["walks"] == "" and m[0]["usdz"] is True and m[0]["device"] == "" and m[0]["ios"] == ""
    assert m[0]["logic"] is True                                            # the tests of the app's logic run once, on the reference

    r, m = plan(tmp_path, "devices: all\n")
    assert [x["slug"] for x in m] == ["reference", "ios18", "small", "ipad"]
    assert m[1]["device"] == "iPhone 16e" and m[1]["ios"] == "18" and m[1]["walks"] == "test1Light test2Dark"
    assert m[2]["walks"] == "test1Light" and not m[1]["usdz"] and not m[2]["usdz"]
    assert m[3]["device"] == "iPad*" and m[3]["walks"] == "test1Light"
    assert [x["logic"] for x in m] == [True, False, False, False]

    r, m = plan(tmp_path, "only: dark\ndevices: all\n")
    assert [x["walks"] for x in m] == ["test2Dark"] * 4

    r, m = plan(tmp_path, "only: night\n")
    assert r.returncode != 0 and "night" in r.stderr


# ------------------------------------------------------------------ a new accessibility finding is seen (ios/ci/audit-compare.py)

def test_a_new_accessibility_finding_fails_and_a_known_one_does_not(tmp_path):
    def run(walk, *more):
        (tmp_path / "audit.txt").write_text(walk, encoding="utf-8")
        return subprocess.run([sys.executable, str(CI / "audit-compare.py"), str(tmp_path / "audit.txt"), str(tmp_path / "accepted.txt"), *more],
                              capture_output=True, text=True)

    known = ("clair-08-accueil\tcontrast\tContrast failed\ttype 48 « Calculateur relié » 120×18 pt\n"
             "clair-18-scan-scanning\tdynamic-type\tDynamic Type font sizes are unsupported\ttype 48 « 34 vues utilisées · mis à jour il y a 7 s » 210×14 pt\n"
             "clair-10-plats\tok\tno finding\t-\n"
             "sombre-08-accueil\tcontrast\tContrast failed\ttype 48 « Calculateur relié » 120×18 pt\n")
    assert run(known).returncode == 0 and "nothing compared" in run(known).stdout              # no accepted list yet
    made = run(known, "--write")
    assert made.returncode == 0 and "3 findings" in made.stdout
    accepted = (tmp_path / "accepted.txt").read_text(encoding="utf-8")
    assert "clair-10-plats" not in accepted and "il y a # s" in accepted                          # "ok" is no finding; figures are left out

    same = run(known.replace("il y a 7 s", "il y a 12 s").replace("210×14", "214×14"))
    assert same.returncode == 0 and "0 new, 0 no longer found" in same.stdout                     # the clock and a size are not a change
    one_walk = run("".join(line + "\n" for line in known.splitlines() if line.startswith("clair-")))
    assert one_walk.returncode == 0 and "0 new, 0 no longer found" in one_walk.stdout             # a single walk is judged on its own screens
    fixed = run(known.replace("clair-08-accueil\tcontrast\tContrast failed\ttype 48 « Calculateur relié » 120×18 pt\n", "clair-08-accueil\tok\tno finding\t-\n"))
    assert fixed.returncode == 0 and "no longer found" in fixed.stdout and "1 no longer found" in fixed.stdout
    # Apple's audit reports some findings of a screen on the light walk one day, on the dark one the next:
    # outside contrast, the two appearances of a screen count as one.
    swapped = run(known.replace("clair-18-scan-scanning", "sombre-18-scan-scanning"))
    assert swapped.returncode == 0 and "0 new" in swapped.stdout
    dark_contrast = run(known + "sombre-16-reglages\tcontrast\tContrast failed\ttype 48 « Tester » 60×18 pt\n")
    assert dark_contrast.returncode == 1                                                            # contrast keeps its appearance
    worse = run(known + "clair-16-reglages\ttext-clipped\tText clipped\ttype 9 « Changer de calculateur » 150×44 pt\n")
    assert worse.returncode == 1 and "NEW finding" in worse.stdout and "Changer de calculateur" in worse.stdout


# ------------------------------------------------------------------ one Xcode for every workflow (ios/ci/select-xcode.sh)

def test_every_workflow_of_the_app_takes_its_xcode_from_one_script(tmp_path):
    for name in ("Xcode_16.4.app", "Xcode_26.1.app", "Xcode_26.3.app", "Xcode_26.10.app", "Xcode_27.0.app"):
        (tmp_path / name).mkdir()

    def select(**env):
        return subprocess.run(["bash", str(CI / "select-xcode.sh")], capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", "XCODE_APPS_DIR": str(tmp_path), **env})

    newest = select()
    assert newest.returncode == 0 and newest.stdout.strip() == f"{tmp_path}/Xcode_26.10.app/Contents/Developer"   # 26.10 is after 26.3
    assert select(XCODE_MAJOR="27").stdout.strip() == f"{tmp_path}/Xcode_27.0.app/Contents/Developer"
    missing = select(XCODE_MAJOR="28")
    assert missing.returncode != 0 and "Xcode_27.0.app" in missing.stderr                                           # it says what is installed
    workflows = CI.parents[1] / ".github" / "workflows"
    for name in ("ios-check.yml", "ios-screens.yml", "ios-testflight.yml"):
        text = (workflows / name).read_text()
        assert "ios/ci/select-xcode.sh" in text and "/Applications/Xcode" not in text, name


# ------------------------------------------------------------------ which checks a push needs (ios/ci/check-plan.py)

def check_plan(files, release="false", event="push", known="true"):
    r = subprocess.run([sys.executable, str(CI / "check-plan.py")], input="\n".join(files) + "\n", capture_output=True, text=True,
                       env={"RELEASE_CALL": release, "EVENT": event, "KNOWN": known, "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    return dict(line.split("=") for line in r.stdout.split())


def jobs(files, **more):
    """The three jobs a push starts, without the quality bench (checked on its own below)."""
    return {k: v for k, v in check_plan(files, **more).items() if k != "engine"}


def test_the_quality_bench_runs_when_the_engine_changes():
    assert check_plan(["backend/reconstruction/refinement.py"])["engine"] == "true"
    assert check_plan(["tools/bench_reference.json"])["engine"] == "true"
    assert check_plan(["backend/app/main.py"])["engine"] == "false"            # the calculator around the engine does not change the models
    assert check_plan(["ios/App/HomeView.swift"])["engine"] == "false"
    assert check_plan(["docs/x.md"], event="workflow_dispatch")["engine"] == "true"
    assert check_plan(["docs/x.md"], release="true")["engine"] == "false"       # a release of the app does not wait for it


def test_a_push_runs_only_the_checks_its_files_need():
    assert jobs(["docs/TEST_REPORT.md", "README.md"]) == {"run": "false", "backend": "false", "ios": "false"}
    assert jobs(["backend/app/main.py"]) == {"run": "true", "backend": "true", "ios": "false"}
    assert jobs(["tools/doctor.py", "docs/x.md"]) == {"run": "true", "backend": "true", "ios": "false"}
    assert check_plan(["colab/photo_express.ipynb"])["backend"] == "true"            # a test reads the notebooks
    assert jobs(["ios/App/HomeView.swift"]) == {"run": "true", "backend": "false", "ios": "true"}
    assert jobs(["ios/ci/pick-simulator.py"]) == {"run": "true", "backend": "true", "ios": "true"}   # tested by the calculator's suite
    assert jobs(["ios/ScanCore/Tests/ScanCoreTests/Vectors/frames.json"]) == {"run": "true", "backend": "true", "ios": "true"}
    assert jobs([".github/workflows/ios-check.yml"]) == {"run": "true", "backend": "true", "ios": "true"}
    assert jobs([".github/workflows/ios-screens.yml"]) == {"run": "true", "backend": "false", "ios": "true"}
    assert jobs([".github/workflows/calculator-windows.yml"]) == {"run": "false", "backend": "false", "ios": "false"}   # it starts itself
    assert jobs(["ios/UITests/RUN.txt"]) == {"run": "false", "backend": "false", "ios": "false"}     # the screen check builds the app itself
    assert jobs(["start-calculator.ps1"]) == {"run": "false", "backend": "false", "ios": "false"}    # the Windows check runs it


def test_everything_is_checked_when_in_doubt_and_a_release_push_steps_aside():
    everything = {"run": "true", "backend": "true", "ios": "true"}
    assert jobs(["docs/x.md"], release="true") == everything                  # the release's own check
    assert jobs(["docs/x.md"], event="workflow_dispatch") == everything
    assert jobs(["docs/x.md"], event="pull_request") == everything
    assert jobs([], known="false") == everything                              # the changes could not be listed
    assert jobs(["ios/RELEASE_NOTES.txt", "ios/App/HomeView.swift"]) == {"run": "false", "backend": "false", "ios": "false"}


# ------------------------------------------------------------------ the same commit is photographed once (ios/ci/screens-plan.py)

def test_a_commit_already_walked_is_not_walked_again(tmp_path):
    def skip(runs, this_run=20):
        (tmp_path / "RUN.txt").write_text("run 1\n")
        (tmp_path / "runs.json").write_text(json.dumps({"workflow_runs": runs}))
        r = subprocess.run([sys.executable, str(CI / "screens-plan.py"), str(tmp_path / "RUN.txt"), str(tmp_path / "runs.json"), str(this_run)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        out = dict(line.split("=", 1) for line in r.stdout.split("\n") if "=" in line)
        assert json.loads(out["matrix"])[0]["slug"] == "reference"                  # the plan itself is unchanged
        return out["skip"]

    me = {"id": 20, "status": "in_progress", "conclusion": None}
    assert skip([me]) == "false"
    assert skip([me, {"id": 12, "status": "completed", "conclusion": "success"}]) == "true"      # walked on the working branch before
    assert skip([me, {"id": 12, "status": "completed", "conclusion": "failure"}]) == "false"     # a failed walk does not count
    assert skip([me, {"id": 12, "status": "completed", "conclusion": "cancelled"}]) == "false"
    assert skip([me, {"id": 19, "status": "in_progress", "conclusion": None}]) == "false"        # a walk in progress may still fail: it does not count
    assert skip([{"id": 20, "status": "completed", "conclusion": "success"}]) == "false"         # its own success is not another walk


# ------------------------------------------------------------------ no release without its pictures (ios/ci/release-gate.py)

def load_gate():
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_gate", CI / "release-gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_release_needs_the_screen_check_of_this_very_app_and_the_right_version():
    gate = load_gate()
    walk = lambda **k: {"sha": "a" * 40, "url": "https://example.invalid/run/1", "same_app": True, "full": True, **k}   # noqa: E731
    notes = "DishPlay Scan 1.7.1 — plusieurs plats à la suite\n"
    ok, said = gate.decide(notes, "1.7.1", [walk()])
    assert ok and "1.7.1" in said[0] and "run/1" in said[0]
    assert gate.decide(notes, "1.7.1", [walk(same_app=False, full=False), walk(url="https://example.invalid/run/2")])[0]   # an older walk of the same app counts
    assert not gate.decide(notes, "1.7.1", [])[0]                                                   # never photographed
    assert not gate.decide(notes, "1.7.1", [walk(same_app=False, full=False)])[0]                   # another app was photographed
    ok, said = gate.decide(notes, "1.7.1", [walk(full=False)])
    assert not ok and "only:" in " ".join(said)                                                     # one walk out of three is not enough
    ok, said = gate.decide(notes, "1.7.0", [walk()])
    assert not ok and "1.7.1" in said[0] and "1.7.0" in said[0]                                     # the notes and the app disagree
    assert not gate.decide("Nouvelle version\n", "1.7.1", [walk()])[0]                              # no version in the notes
    assert not gate.decide(notes, None, [walk()])[0]


def test_the_gate_reads_the_versions_and_the_walks_as_they_are_written():
    gate = load_gate()
    root = CI.parents[1]
    project = (root / "ios" / "project.yml").read_text()
    assert gate.marketing_version(project) and gate.marketing_version(project).count(".") == 2
    first = (root / "ios" / "RELEASE_NOTES.txt").read_text().splitlines()[0]
    assert gate.notes_version(first), first                                          # the notes in the repository name a version
    assert gate.notes_version("DishPlay Scan 1.7.0 — nouvelle apparence") == "1.7.0"
    assert gate.full_walk("run 6\n") and gate.full_walk("devices: all\nrun 7\n")
    assert not gate.full_walk("only: light\nrun 8\n") and not gate.full_walk("run 9\nonly:\tdark\n")
