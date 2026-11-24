"""Compares the accessibility findings of a screen check with the list accepted for the app
(ios/UITests/audit-baseline.txt), so that a new finding is seen instead of being lost among the known ones.

    python3 ios/ci/audit-compare.py AUDIT.txt BASELINE.txt            compare; exit code 1 on a new finding
    python3 ios/ci/audit-compare.py AUDIT.txt BASELINE.txt --write    make BASELINE.txt from this walk

AUDIT.txt is what the walk writes: one finding per line, `screen <tab> kind <tab> description <tab> element`.
A finding is its screen, its kind and its element. Sizes and figures are left out, because they change with the
clock and from one run to the next ("mis à jour il y a 7 s", "354×74 pt"). Only the screens present in AUDIT.txt
are compared: a single walk (`only: light`) is judged on its own screens.

A new finding means either that the app got worse, or that the finding is accepted: then the baseline is made
again with --write from a full walk and committed, which a person can read in the diff. A finding that went
away is only reported.
"""
import re
import sys
from pathlib import Path

HEADER = ("# Accessibility findings accepted for the app, one per line: screen, kind, element (figures replaced by #).\n"
          "# Made by ios/ci/audit-compare.py --write from a full walk of the screen check; see docs/SCREEN_CHECK.md.\n")


def finding(line: str):
    """(screen, kind, element) of one line of the walk; None for a line that is no finding."""
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 4 or parts[1] == "ok":
        return None
    element = re.sub(r"\s*\d+×\d+ pt$", "", parts[3])      # the size of the element
    element = re.sub(r"\d+", "#", element)                  # counters, ages, the type number of the element
    return parts[0], parts[1], element


def read_walk(text: str):
    found, screens = set(), set()
    for line in text.splitlines():
        if not line.strip():
            continue
        screens.add(line.split("\t", 1)[0])
        f = finding(line)
        if f:
            found.add(f)
    return found, screens


def read_baseline(text: str):
    return {tuple(line.split("\t")) for line in text.splitlines() if line.strip() and not line.startswith("#")}


def compare(walk_text: str, baseline_text: str):
    """(new findings, findings that went away), both sorted."""
    found, screens = read_walk(walk_text)
    accepted = {f for f in read_baseline(baseline_text) if f[0] in screens}
    return sorted(found - accepted), sorted(accepted - found)


def main() -> None:
    walk = Path(sys.argv[1]).read_text(encoding="utf-8")
    baseline = Path(sys.argv[2])
    if "--write" in sys.argv:
        found, _ = read_walk(walk)
        baseline.write_text(HEADER + "".join("\t".join(f) + "\n" for f in sorted(found)), encoding="utf-8")
        print(f"{len(found)} findings written to {baseline}")
        return
    if not baseline.exists():
        print(f"no accepted list yet ({baseline}): nothing compared")
        return
    new, gone = compare(walk, baseline.read_text(encoding="utf-8"))
    for f in gone:
        print("no longer found:   " + " | ".join(f))
    for f in new:
        print("NEW finding:       " + " | ".join(f))
    print(f"{len(new)} new, {len(gone)} no longer found")
    if new:
        sys.exit(1)


if __name__ == "__main__":
    main()
