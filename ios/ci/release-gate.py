"""Stops a TestFlight release that was not looked at (workflow ios-testflight.yml, job "gate").

A release is asked for by changing ios/RELEASE_NOTES.txt on main. Before anything is sent to Apple:
  1. the version written on the first line of the notes must be the app's MARKETING_VERSION (ios/project.yml);
  2. the screen check (workflow "DishPlay Scan — screens") must have SUCCEEDED on a commit whose app is the same
     as the release's (everything under ios/ except the notes, RUN.txt, the audit baseline and ios/ci), with the
     three walks on the reference iPhone (no "only:" line in its ios/UITests/RUN.txt).
Version 1.7.0 reached the testers four minutes before its pictures existed: nothing obliged anyone to wait.

    python3 ios/ci/release-gate.py            (in a checkout with full history; needs `gh` and GH_TOKEN)

It cannot check that somebody LOOKED at the pictures: only that they exist for this very app.
"""
import json
import os
import re
import subprocess
import sys

NOT_THE_APP = ["ios/RELEASE_NOTES.txt", "ios/UITests/RUN.txt", "ios/UITests/audit-baseline.txt", "ios/ci"]


def notes_version(first_line: str):
    m = re.search(r"\d+\.\d+(?:\.\d+)?", first_line)
    return m.group(0) if m else None


def marketing_version(project_yml: str):
    m = re.search(r'^\s*MARKETING_VERSION:\s*"?([0-9][0-9.]*)"?\s*$', project_yml, re.M)
    return m.group(1) if m else None


def full_walk(run_txt: str) -> bool:
    """The three walks were asked for: no line restricts them to one."""
    return not re.search(r"^only:[ \t]*\S+", run_txt, re.M)


def decide(first_line: str, marketing: str, walks: list) -> tuple:
    """walks: successful runs of the screen check, newest first, each {"sha", "url", "same_app", "full"}.
    Returns (ok, lines to print)."""
    said = notes_version(first_line)
    if not marketing:
        return False, ["MARKETING_VERSION was not found in ios/project.yml."]
    if said != marketing:
        return False, [f"The notes announce version {said or '(none)'} but the app is version {marketing}.",
                       "Write the app's version on the first line of ios/RELEASE_NOTES.txt, or change MARKETING_VERSION "
                       "in ios/project.yml (and run the screen check again: the app changes)."]
    same = [w for w in walks if w["same_app"]]
    good = [w for w in same if w["full"]]
    if good:
        return True, [f"Version {marketing}. Screens checked on this very app: {good[0]['url']} (commit {good[0]['sha'][:7]})."]
    if same:
        return False, [f"The screen check ran on this app ({same[0]['url']}) but not the three walks (its RUN.txt had an \"only:\" line).",
                       "Remove the \"only:\" line of ios/UITests/RUN.txt, push, wait for the walks, look at the pictures, then release."]
    return False, ["No successful screen check exists for this app: the pictures of what would be sent do not exist.",
                   "Change ios/UITests/RUN.txt (no \"only:\" line) on the working branch, push, wait for the three walks, "
                   "LOOK at the pictures, then change ios/RELEASE_NOTES.txt on main without touching the app."]


def sh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def same_app(sha: str) -> bool:
    if sh("git", "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        sh("git", "fetch", "--quiet", "origin", sha)
    if sh("git", "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        return False
    return sh("git", "diff", "--quiet", sha, "HEAD", "--", "ios", *[f":(exclude){p}" for p in NOT_THE_APP]).returncode == 0


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    r = sh("gh", "api", f"repos/{repo}/actions/workflows/ios-screens.yml/runs?status=success&per_page=40")
    if r.returncode != 0:
        print("The list of screen checks could not be read:", r.stderr.strip())
        return 1
    walks = []
    for run in json.loads(r.stdout).get("workflow_runs", []):
        sha = run["head_sha"]
        same = same_app(sha)
        run_txt = sh("git", "show", f"{sha}:ios/UITests/RUN.txt").stdout if same else ""
        walks.append({"sha": sha, "url": run["html_url"], "same_app": same, "full": same and full_walk(run_txt)})
    first_line = open("ios/RELEASE_NOTES.txt", encoding="utf-8").readline()
    ok, lines = decide(first_line, marketing_version(open("ios/project.yml", encoding="utf-8").read()), walks)
    print("\n".join(lines))
    if not ok and os.environ.get("UPLOAD", "true") != "true":
        print("(Build only, nothing is sent to Apple: the release gate does not stop it.)")
        return 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
